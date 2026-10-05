from __future__ import annotations

import io
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import quote

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import DailyBar, Instrument, QualityStatus


class MarketDataError(RuntimeError):
    pass


@dataclass
class DataQuality:
    status: QualityStatus
    messages: list[str]


class MarketDataProvider(Protocol):
    name: str

    def history(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...


class YahooChartProvider:
    name = "yahoo"
    base_urls = (
        "https://query2.finance.yahoo.com/v8/finance/chart",
        "https://query1.finance.yahoo.com/v8/finance/chart",
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
    }

    def history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        period1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        period2 = int(
            datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()
        )
        params = {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        response = None
        last_error: Exception | None = None
        for attempt, base_url in enumerate(self.base_urls):
            try:
                response = httpx.get(
                    f"{base_url}/{quote(symbol, safe='')}",
                    params=params,
                    headers=self.headers,
                    timeout=25,
                    follow_redirects=True,
                )
                response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                last_error = exc
                response = None
                if attempt == 0:
                    time.sleep(1)
        if response is None:
            raise MarketDataError(f"Yahoo 两个域名均无法获取 {symbol}: {last_error}")
        result = response.json().get("chart", {}).get("result")
        if not result:
            raise MarketDataError(f"Yahoo 没有返回 {symbol} 的数据")
        payload = result[0]
        timestamps = payload.get("timestamp") or []
        quote_data = (payload.get("indicators", {}).get("quote") or [{}])[0]
        adj_data = (payload.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
        if not timestamps:
            raise MarketDataError(f"{symbol} 没有日线")
        tz_name = payload.get("meta", {}).get("exchangeTimezoneName", "UTC")
        index = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(tz_name).date
        frame = pd.DataFrame(
            {
                "open": quote_data.get("open"),
                "high": quote_data.get("high"),
                "low": quote_data.get("low"),
                "close": quote_data.get("close"),
                "adjusted_close": adj_data or quote_data.get("close"),
                "volume": quote_data.get("volume"),
            },
            index=pd.Index(index, name="date"),
        )
        frame["split_factor"] = 1.0
        for event in (payload.get("events", {}).get("splits") or {}).values():
            event_date = pd.Timestamp(event["date"], unit="s", tz="UTC").tz_convert(tz_name).date()
            if event_date in frame.index:
                frame.loc[event_date, "split_factor"] = float(event.get("numerator", 1)) / float(
                    event.get("denominator", 1)
                )
        return _clean_frame(frame)


class StooqProvider:
    name = "stooq"

    def history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if symbol.startswith("^") or symbol.endswith((".HK", ".KS", ".SZ")):
            raise MarketDataError("Stooq fallback does not support this symbol mapping")
        stooq_symbol = f"{symbol.lower()}.us"
        url = "https://stooq.com/q/d/l/"
        response = httpx.get(
            url,
            params={"s": stooq_symbol, "d1": start.strftime("%Y%m%d"), "d2": end.strftime("%Y%m%d"), "i": "d"},
            timeout=25,
            follow_redirects=True,
        )
        response.raise_for_status()
        frame = pd.read_csv(io.StringIO(response.text))
        if frame.empty or "Date" not in frame:
            raise MarketDataError(f"Stooq 没有返回 {symbol} 的数据")
        frame.columns = [column.lower() for column in frame.columns]
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame = frame.set_index("date")
        frame["adjusted_close"] = frame["close"]
        frame["split_factor"] = 1.0
        return _clean_frame(frame)


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["open", "high", "low", "close", "adjusted_close", "volume", "split_factor"]
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(
        subset=["open", "high", "low", "close", "adjusted_close"]
    ).copy()
    frame["volume"] = frame["volume"].fillna(0)
    frame["split_factor"] = frame["split_factor"].fillna(1.0)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index().copy()
    return frame.replace([np.inf, -np.inf], np.nan).dropna(subset=["close"])


def validate_frame(frame: pd.DataFrame, expected_end: date | None = None) -> DataQuality:
    messages: list[str] = []
    if frame.empty:
        return DataQuality(QualityStatus.BLOCKED, ["没有可用行情"])
    invalid_ohlc = (
        (frame["low"] > frame[["open", "close"]].min(axis=1))
        | (frame["high"] < frame[["open", "close"]].max(axis=1))
        | (frame[["open", "high", "low", "close", "adjusted_close"]] <= 0).any(axis=1)
    )
    if invalid_ohlc.any():
        messages.append(f"发现 {int(invalid_ohlc.sum())} 条无效 OHLC")
    daily = frame["adjusted_close"].pct_change()
    if (daily.abs() > 0.8).any():
        messages.append("发现超过 80% 的复权日涨跌，需核对拆合股")
    if expected_end and (expected_end - frame.index[-1]).days > 5:
        messages.append(f"最新行情停留在 {frame.index[-1]}")
    if invalid_ohlc.any() or (expected_end and (expected_end - frame.index[-1]).days > 10):
        return DataQuality(QualityStatus.BLOCKED, messages)
    return DataQuality(QualityStatus.WARNING if messages else QualityStatus.OK, messages)


def compare_sources(primary: pd.DataFrame, secondary: pd.DataFrame) -> DataQuality:
    joined = primary[["adjusted_close"]].join(
        secondary[["adjusted_close"]], how="inner", lsuffix="_primary", rsuffix="_secondary"
    ).tail(60)
    if len(joined) < 15:
        return DataQuality(QualityStatus.WARNING, ["交叉数据重叠不足 15 日"])
    primary_return = joined["adjusted_close_primary"].pct_change()
    secondary_return = joined["adjusted_close_secondary"].pct_change()
    correlation = primary_return.corr(secondary_return)
    if pd.isna(correlation) or correlation < 0.95:
        return DataQuality(QualityStatus.BLOCKED, [f"双源收益相关性仅 {correlation:.3f}"])
    return DataQuality(QualityStatus.OK, [])


def fetch_with_validation(symbol: str, start: date, end: date, use_fallback: bool = True) -> tuple[pd.DataFrame, str, DataQuality]:
    yahoo = YahooChartProvider()
    try:
        primary = yahoo.history(symbol, start, end)
    except (httpx.HTTPError, MarketDataError, ValueError):
        if not use_fallback:
            raise
        fallback = StooqProvider()
        try:
            frame = fallback.history(symbol, start, end)
        except (httpx.HTTPError, MarketDataError, ValueError) as exc:
            raise MarketDataError(f"Yahoo 与 Stooq 均无法获取 {symbol}: {exc}") from exc
        quality = validate_frame(frame, end)
        quality.messages.append("Yahoo 不可用，已切换到 Stooq；当前缺少双源校验")
        if quality.status == QualityStatus.OK:
            quality.status = QualityStatus.WARNING
        return frame, fallback.name, quality
    quality = validate_frame(primary, end)
    if use_fallback:
        try:
            secondary = StooqProvider().history(symbol, start, end)
            comparison = compare_sources(primary, secondary)
            if comparison.status == QualityStatus.BLOCKED:
                quality = comparison
            elif comparison.messages:
                quality.messages.extend(comparison.messages)
        except (httpx.HTTPError, MarketDataError, ValueError):
            quality.messages.append("备用数据源不可用，当前仅完成单源校验")
            if quality.status == QualityStatus.OK:
                quality.status = QualityStatus.WARNING
    return primary, yahoo.name, quality


def upsert_bars(db: Session, instrument: Instrument, frame: pd.DataFrame, source: str, quality: DataQuality) -> int:
    rows = [
        {
            "instrument_id": instrument.id,
            "date": index,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "adjusted_close": float(row.adjusted_close),
            "volume": float(row.volume or 0),
            "split_factor": float(row.split_factor or 1),
            "source": source,
            "quality_status": quality.status,
            "fetched_at": datetime.now(timezone.utc),
        }
        for index, row in frame.iterrows()
    ]
    if not rows:
        return 0
    if db.bind and db.bind.dialect.name == "postgresql":
        statement = pg_insert(DailyBar).values(rows)
        statement = statement.on_conflict_do_update(
            constraint="uq_bar_source_date",
            set_={key: getattr(statement.excluded, key) for key in rows[0] if key not in {"instrument_id", "date", "source"}},
        )
        db.execute(statement)
    else:
        for values in rows:
            bar = db.scalar(
                select(DailyBar).where(
                    DailyBar.instrument_id == values["instrument_id"],
                    DailyBar.date == values["date"],
                    DailyBar.source == values["source"],
                )
            )
            if bar:
                for key, value in values.items():
                    setattr(bar, key, value)
            else:
                db.add(DailyBar(**values))
    db.commit()
    return len(rows)
