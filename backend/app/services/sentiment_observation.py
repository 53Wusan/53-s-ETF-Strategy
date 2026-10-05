"""Read-only observation payloads; never update strategy state or send alerts."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pandas_market_calendars as mcal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyBar, Instrument, QualityStatus
from app.services.sentiment import (
    COMPONENTS,
    FACTOR_WEIGHTS,
    INDEX_VERSION,
    build_components,
    score_index,
)


def observation(db: Session, instrument: Instrument, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    result = {
        "symbol": instrument.symbol, "name": instrument.name, "version": INDEX_VERSION,
        "weights": dict(FACTOR_WEIGHTS), "status": "missing", "message": "尚无本地行情",
        "data_date": None, "expected_date": None, "latest": None, "points": [],
    }
    rows = list(db.scalars(select(DailyBar).where(DailyBar.instrument_id == instrument.id)
                          .order_by(DailyBar.date, DailyBar.id)))
    if not rows:
        return result
    # Match the existing source preference deterministically, without hiding blocked Yahoo bars.
    selected = {}
    for row in sorted(rows, key=lambda r: (r.date, {"yahoo": 0, "stooq": 1}.get(r.source, 2), r.id)):
        selected.setdefault(row.date, row)
    try:
        calendar = mcal.get_calendar(instrument.calendar)
        schedule = calendar.schedule(start_date=min(selected), end_date=now.date() + timedelta(days=1))
        closed = schedule[schedule.market_close <= pd.Timestamp(now)]
    except (ValueError, KeyError, RuntimeError):
        result.update(status="blocked", message="无法核验交易日历，暂停计算")
        return result
    if closed.empty:
        result.update(status="blocked", message="没有可确认的已收盘交易日")
        return result
    expected = closed.index[-1].date()
    result["expected_date"] = str(expected)
    selected = {day: row for day, row in selected.items() if day <= expected}
    if not selected:
        return result
    last = max(selected)
    result["data_date"] = str(last)
    missing = set(closed.loc[str(min(selected)):str(last)].index.date) - set(selected)
    if missing or any(row.quality_status == QualityStatus.BLOCKED for row in selected.values()):
        result.update(status="blocked", message="历史行情缺少交易日或被数据质量检查阻断，暂停计算")
        return result
    frame = pd.DataFrame([{
        "date": day, **{key: getattr(row, key) for key in
        ("open", "high", "low", "close", "adjusted_close", "volume")}
    } for day, row in selected.items()]).set_index("date")
    try:
        scored = score_index(build_components(frame))
    except ValueError:
        result.update(status="blocked", message="行情存在无效价格、缺失值或零成交量，暂停计算")
        return result
    def number(value):
        return float(value) if pd.notna(value) else None
    result["points"] = [{"date": str(day), "score": number(row["score"])}
                        for day, row in scored.tail(756).iterrows()]
    latest = scored.iloc[-1]
    if pd.isna(latest["score"]):
        result.update(status="insufficient", message="有效历史或分项不足，暂不显示指数")
        return result
    result["latest"] = {
        "score": float(latest["score"]),
        "components": {key: number(latest[key]) for key in COMPONENTS},
        "contributions": {key: number(latest[key] * FACTOR_WEIGHTS[key]) for key in COMPONENTS},
    }
    warning = any(row.quality_status == QualityStatus.WARNING for row in selected.values())
    result.update(status="stale" if last < expected else "warning" if warning else "ok",
                  message="行情未更新，以下仅为历史观察" if last < expected else
                  "行情带质量警告，请谨慎解读" if warning else "已更新至最近收盘日")
    return result
