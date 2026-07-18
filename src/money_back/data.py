from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .models import DataIssue


ETF_SYMBOLS = {
    "159516": "sz159516",
    "513120": "sh513120",
    "159206": "sz159206",
    "562500": "sh562500",
    "515880": "sh515880",
    "561380": "sh561380",
}

INDEX_SYMBOLS = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
    "科创50": "sh000688",
    "上证50": "sh000016",
    "沪深300": "sh000300",
    "中证500": "sh000905",
    "中证1000": "sh000852",
}

CORE_GATE_INDICES = ("上证指数", "深证成指", "创业板指", "科创50")
TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


@dataclass(frozen=True)
class MarketDataBundle:
    adjusted: dict[str, pd.DataFrame]
    raw: dict[str, pd.DataFrame]
    source_manifest: pd.DataFrame


def _request_json(url: str, retries: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Market-data request failed: {url}") from last_error


def _fetch_chunk(
    symbol: str,
    start: str,
    end: str,
    *,
    adjusted: bool,
    limit: int = 640,
) -> tuple[str, list[list[str]], str]:
    adjustment = "qfq" if adjusted else ""
    # Tencent expects the sixth comma-delimited slot even for unadjusted data.
    pieces = [symbol, "day", start, end, str(limit), adjustment]
    parameter = ",".join(pieces)
    url = TENCENT_URL + "?" + urllib.parse.urlencode({"param": parameter})
    payload = _request_json(url)
    security = payload["data"][symbol]
    key = "qfqday" if adjusted and security.get("qfqday") else "day"
    rows = security.get(key) or []
    name = security.get("qt", {}).get(symbol, [None, symbol])[1]
    return name, rows, url


def fetch_daily_prices(
    symbol: str,
    start: str,
    end: str,
    *,
    adjusted: bool,
    cache_dir: str | Path = "data/cache",
    refresh: bool = False,
) -> tuple[str, pd.DataFrame, dict]:
    """Fetch paginated daily OHLCV and preserve source metadata."""
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    suffix = "qfq" if adjusted else "raw"
    csv_path = cache_path / f"{symbol}_{start}_{end}_{suffix}.csv"
    meta_path = cache_path / f"{symbol}_{start}_{end}_{suffix}.json"

    legacy_csv = cache_path / f"{symbol}_{start}_{end}.csv"
    legacy_meta = cache_path / f"{symbol}_{start}_{end}.json"
    if adjusted and not csv_path.exists() and legacy_csv.exists() and legacy_meta.exists():
        csv_path, meta_path = legacy_csv, legacy_meta

    if csv_path.exists() and meta_path.exists() and not refresh:
        frame = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        metadata.setdefault("adjustment", suffix)
        return metadata["name"], frame, metadata

    rows_all: list[list[str]] = []
    current_end = end
    name = symbol
    last_url = ""
    while True:
        name, rows, last_url = _fetch_chunk(
            symbol, start, current_end, adjusted=adjusted
        )
        if not rows:
            break
        rows_all = rows + rows_all
        first_date = datetime.strptime(rows[0][0], "%Y-%m-%d")
        if rows[0][0] <= start or len(rows) < 640:
            break
        current_end = (first_date - timedelta(days=1)).strftime("%Y-%m-%d")
        time.sleep(0.05)

    deduplicated = {row[0]: row for row in rows_all}
    rows = [deduplicated[key] for key in sorted(deduplicated) if start <= key <= end]
    if not rows:
        raise ValueError(f"No prices for {symbol} between {start} and {end}")

    columns = ["date", "open", "close", "high", "low", "volume"]
    frame = pd.DataFrame([row[:6] for row in rows], columns=columns)
    frame["date"] = pd.to_datetime(frame["date"])
    for column in columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.set_index("date").sort_index()

    metadata = {
        "symbol": symbol,
        "name": name,
        "start": start,
        "end": end,
        "rows": len(frame),
        "source": TENCENT_URL,
        "request_url": last_url,
        "adjustment": suffix,
        "downloaded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    frame.reset_index().to_csv(csv_path, index=False, encoding="utf-8-sig")
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return name, frame, metadata


def load_market_data(
    start: str,
    end: str,
    *,
    cache_dir: str | Path = "data/cache",
    refresh: bool = False,
    include_raw: bool = True,
) -> MarketDataBundle:
    adjusted_frames: dict[str, pd.DataFrame] = {}
    raw_frames: dict[str, pd.DataFrame] = {}
    records: list[dict] = []
    for label, symbol in {**ETF_SYMBOLS, **INDEX_SYMBOLS}.items():
        name, adjusted_frame, adjusted_meta = fetch_daily_prices(
            symbol, start, end, adjusted=True, cache_dir=cache_dir, refresh=refresh
        )
        adjusted_frames[label] = adjusted_frame
        records.append(
            {
                "label": label,
                "symbol": symbol,
                "name": name,
                "series": "adjusted",
                "first_date": adjusted_frame.index.min().date().isoformat(),
                "last_date": adjusted_frame.index.max().date().isoformat(),
                "rows": len(adjusted_frame),
                "source": adjusted_meta["source"],
            }
        )
        if include_raw:
            raw_name, raw_frame, raw_meta = fetch_daily_prices(
                symbol, start, end, adjusted=False, cache_dir=cache_dir, refresh=refresh
            )
            raw_frames[label] = raw_frame
            records.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "name": raw_name,
                    "series": "raw",
                    "first_date": raw_frame.index.min().date().isoformat(),
                    "last_date": raw_frame.index.max().date().isoformat(),
                    "rows": len(raw_frame),
                    "source": raw_meta["source"],
                }
            )
    return MarketDataBundle(adjusted_frames, raw_frames, pd.DataFrame(records))


def field_matrix(
    frames: dict[str, pd.DataFrame],
    labels: Iterable[str],
    field: str,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    return pd.DataFrame({label: frames[label][field].reindex(calendar) for label in labels})


def validate_price_frame(
    symbol: str,
    frame: pd.DataFrame,
    reference_calendar: pd.DatetimeIndex | None = None,
) -> list[DataIssue]:
    issues: list[DataIssue] = []
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        issues.append(DataIssue("missing_columns", "critical", f"Missing {missing}", symbol))
        return issues
    duplicate_count = int(frame.index.duplicated().sum())
    if duplicate_count:
        issues.append(
            DataIssue(
                "duplicate_dates",
                "critical",
                "Duplicate trading dates",
                symbol,
                evidence={"count": duplicate_count},
            )
        )
    invalid_ohlc = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    for date in frame.index[invalid_ohlc][:20]:
        issues.append(
            DataIssue(
                "invalid_ohlc",
                "high",
                "OHLC relationship or positivity check failed",
                symbol,
                pd.Timestamp(date).date().isoformat(),
            )
        )
    if not frame.index.is_monotonic_increasing:
        issues.append(DataIssue("unsorted_dates", "high", "Dates are not sorted", symbol))
    if reference_calendar is not None and not frame.empty:
        expected = reference_calendar[
            (reference_calendar >= frame.index.min())
            & (reference_calendar <= frame.index.max())
        ]
        missing_dates = expected.difference(frame.index)
        for date in missing_dates[:20]:
            issues.append(
                DataIssue(
                    "trading_day_gap",
                    "medium",
                    "Price series is missing a date present in the reference exchange calendar",
                    symbol,
                    pd.Timestamp(date).date().isoformat(),
                )
            )
    return issues


def compare_close_sources(
    symbol: str,
    left: pd.Series,
    right: pd.Series,
    *,
    tolerance: float = 0.005,
) -> list[DataIssue]:
    aligned = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
    if aligned.empty:
        return [DataIssue("no_cross_source_overlap", "high", "No overlapping prices", symbol)]
    relative = (aligned["left"] / aligned["right"] - 1.0).abs()
    failures = relative[relative > tolerance]
    issues: list[DataIssue] = []
    for date, value in failures.head(20).items():
        issues.append(
            DataIssue(
                "cross_source_price_divergence",
                "high",
                f"Close prices differ by {value:.2%}",
                symbol,
                pd.Timestamp(date).date().isoformat(),
                {"relative_difference": float(value), "tolerance": tolerance},
            )
        )
    return issues


def detect_adjustment_jumps(
    raw_close: pd.Series,
    adjusted_close: pd.Series,
    symbol: str | None = None,
) -> list[DataIssue]:
    aligned = pd.concat([raw_close.rename("raw"), adjusted_close.rename("adjusted")], axis=1).dropna()
    ratio = aligned["adjusted"] / aligned["raw"]
    changes = ratio.pct_change().abs()
    failures = changes[changes > 0.20]
    return [
        DataIssue(
            "adjustment_factor_jump",
            "medium",
            f"Adjustment factor changed by {value:.2%}",
            symbol,
            date=pd.Timestamp(date).date().isoformat(),
            evidence={"change": float(value)},
        )
        for date, value in failures.head(20).items()
    ]
