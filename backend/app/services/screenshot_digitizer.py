from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import DailyBar, Instrument, ReferenceSignal

MSG_TO_SYMBOL = {
    "1066289984902161302": "KORU",
    "2507618757169382912": "NAIL",
    "3281559074256103878": "FAS",
    "3475732039076517294": "TQQQ",
    "4161008092749337131": "07447",
    "4468304927286804262": "CURE",
    "4920586881210992482": "YINN",
    "5173999301282004458": "DFEN",
    "5433453679136562053": "FNGU",
    "5690875853550187789": "GDXU",
    "7342618740545342846": "LABU",
    "7470384078476838832": "SPMO",
    "7646503226294721667": "07234",
    "8331145056317579201": "SOXL",
}
CHART_BOUNDS = (113, 82, 2054, 409)
REFERENCE_STARTS = {
    "KORU": date(2024, 7, 29),
    "NAIL": date(2024, 4, 23),
    "FAS": date(2024, 4, 23),
    "TQQQ": date(2024, 4, 23),
    "07447": date(2025, 10, 21),
    "CURE": date(2024, 6, 24),
    "YINN": date(2024, 4, 23),
    "DFEN": date(2024, 4, 23),
    "FNGU": date(2024, 6, 17),
    "GDXU": date(2024, 6, 24),
    "LABU": date(2024, 4, 23),
    "SPMO": date(2025, 7, 22),
    "07234": date(2024, 10, 2),
    "SOXL": date(2024, 6, 17),
}
REFERENCE_END = date(2026, 8, 19)
LATEST_LABELS = {
    "KORU": -3.0,
    "NAIL": -42.0,
    "FAS": 58.0,
    "TQQQ": 43.0,
    "07447": 25.0,
    "CURE": 61.0,
    "YINN": -24.0,
    "DFEN": 53.0,
    "FNGU": 57.0,
    "GDXU": -30.0,
    "LABU": 56.0,
    "SPMO": 48.0,
    "07234": 28.0,
    "SOXL": -32.0,
}


def _detect_horizontal_bounds(image: np.ndarray) -> tuple[int, int]:
    _, top, _, bottom = CHART_BOUNDS
    row = image[(top + bottom) // 2]
    coloured = (row[:, 0] < 245) | (row[:, 1] < 245) | (row[:, 2] < 245)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(coloured):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start > 500:
                runs.append((start, index - 1))
            start = None
    if start is not None and len(coloured) - start > 500:
        runs.append((start, len(coloured) - 1))
    if not runs:
        return CHART_BOUNDS[0], CHART_BOUNDS[2]
    return max(runs, key=lambda item: item[1] - item[0])


def extract_curve(
    path: str | Path,
    symbol: str | None = None,
    trading_dates: list[date] | pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    image = np.asarray(Image.open(path).convert("RGB"))
    _, top, _, bottom = CHART_BOUNDS
    left, right = _detect_horizontal_bounds(image)
    crop = image[top : bottom + 1, left : right + 1]
    red, green, blue = crop[..., 0], crop[..., 1], crop[..., 2]
    purple = (red > 70) & (blue > 140) & ((blue.astype(int) - green.astype(int)) > 45) & (
        (red.astype(int) - green.astype(int)) > 10
    )
    y_values = np.full(purple.shape[1], np.nan)
    spreads = np.full(purple.shape[1], np.nan)
    for x in range(purple.shape[1]):
        ys = np.flatnonzero(purple[:, x])
        if len(ys):
            y_values[x] = float(np.median(ys))
            spreads[x] = float(np.std(ys))
    series = pd.Series(y_values).interpolate(limit=12, limit_direction="both").rolling(3, center=True, min_periods=1).median()
    spread_series = pd.Series(spreads).interpolate(limit_direction="both").fillna(0)
    start_date = REFERENCE_STARTS.get(symbol or "KORU", REFERENCE_STARTS["KORU"])
    dates = pd.DatetimeIndex(trading_dates) if trading_dates is not None else pd.bdate_range(start_date, REFERENCE_END)
    day_offsets = np.array([(timestamp.date() - start_date).days for timestamp in dates], dtype=float)
    x_positions = day_offsets / max(1, (REFERENCE_END - start_date).days) * (len(series) - 1)
    sampled_y = np.interp(x_positions, np.arange(len(series)), series)
    sampled_spread = np.interp(x_positions, np.arange(len(spread_series)), spread_series)
    values = 100 - sampled_y / max(1, crop.shape[0] - 1) * 200
    error = sampled_spread / max(1, crop.shape[0] - 1) * 200
    result = pd.DataFrame(
        {
            "date": dates.date,
            "value": np.clip(values, -100, 100),
            "extraction_error": error,
            "manually_verified": False,
        }
    )
    if symbol in LATEST_LABELS and REFERENCE_END in set(result["date"]):
        latest = result["date"] == REFERENCE_END
        result.loc[latest, ["value", "extraction_error", "manually_verified"]] = [
            LATEST_LABELS[symbol],
            0.0,
            True,
        ]
    return result


def digitize_all(directory: str | Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with SessionLocal() as db:
        instruments = {item.symbol: item for item in db.scalars(select(Instrument))}
        for path in Path(directory).glob("*.jpg"):
            match = re.search(r"MsgID=(\d+)", path.name)
            symbol = MSG_TO_SYMBOL.get(match.group(1)) if match else None
            if not symbol or symbol not in instruments:
                continue
            instrument = instruments[symbol]
            trading_dates = list(
                db.scalars(
                    select(DailyBar.date).where(
                        DailyBar.instrument_id == instrument.id,
                        DailyBar.source == "yahoo",
                        DailyBar.date >= REFERENCE_STARTS[symbol],
                        DailyBar.date <= REFERENCE_END,
                    ).order_by(DailyBar.date)
                )
            )
            if trading_dates and trading_dates[-1] != REFERENCE_END:
                trading_dates.append(REFERENCE_END)
            frame = extract_curve(path, symbol=symbol, trading_dates=trading_dates or None)
            db.execute(delete(ReferenceSignal).where(ReferenceSignal.instrument_id == instrument.id))
            for row in frame.itertuples(index=False):
                existing = db.scalar(
                    select(ReferenceSignal).where(
                        ReferenceSignal.instrument_id == instrument.id,
                        ReferenceSignal.date == row.date,
                    )
                )
                values = {
                    "value": float(row.value),
                    "extraction_error": float(row.extraction_error),
                    "manually_verified": bool(row.manually_verified),
                    "source_file": path.name,
                }
                if existing:
                    for key, value in values.items():
                        setattr(existing, key, value)
                else:
                    db.add(ReferenceSignal(instrument_id=instrument.id, date=row.date, **values))
            counts[symbol] = len(frame)
        db.commit()
    return counts
