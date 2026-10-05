"""Append validated local raw quotes to the ledger, never adjusted fill prices."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyBar, Instrument, QualityStatus
from app.services.market_data import validate_frame
from app.services.research_cockpit import INPUT_SYMBOLS, _active_data


def sync_local_quotes(db: Session) -> int:
    active, cutoff, _ = _active_data()
    if active is None:
        return 0
    added = 0
    for instrument in db.scalars(select(Instrument).where(Instrument.symbol.in_(INPUT_SYMBOLS))):
        path = active / f"{instrument.symbol}_public_snapshot.csv"
        if not path.exists():
            continue
        bars = pd.read_csv(path, parse_dates=["date"]).set_index("date").loc[:cutoff]
        if bars.empty or bars.index.has_duplicates or validate_frame(bars).status != QualityStatus.OK:
            raise ValueError(f"{instrument.symbol} 原始行情质量不足，暂停账本同步")
        existing = set(db.scalars(select(DailyBar.date).where(DailyBar.instrument_id == instrument.id)))
        for day, row in bars.iterrows():
            if day.date() in existing:
                continue
            db.add(DailyBar(instrument_id=instrument.id, date=day.date(),
                            **{k: float(row[k]) for k in ("open", "high", "low", "close", "adjusted_close", "volume", "split_factor")},
                            source="desk_public", quality_status=QualityStatus.OK))
            added += 1
    db.commit()
    return added
