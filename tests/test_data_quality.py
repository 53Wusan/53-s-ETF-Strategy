from __future__ import annotations

import pandas as pd

from money_back.data import (
    compare_close_sources,
    detect_adjustment_jumps,
    validate_price_frame,
)


def test_invalid_ohlc_is_flagged() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-02"])
    frame = pd.DataFrame(
        {"open": [10, 10], "high": [9, 11], "low": [8, 9], "close": [10, 10], "volume": [1, 1]},
        index=dates,
    )
    codes = {issue.code for issue in validate_price_frame("A", frame)}
    assert "duplicate_dates" in codes
    assert "invalid_ohlc" in codes


def test_cross_source_divergence_is_flagged() -> None:
    dates = pd.bdate_range("2026-01-01", periods=2)
    issues = compare_close_sources(
        "A",
        pd.Series([100.0, 101.0], index=dates),
        pd.Series([100.0, 90.0], index=dates),
    )
    assert issues[0].code == "cross_source_price_divergence"


def test_reference_calendar_gap_is_flagged() -> None:
    calendar = pd.bdate_range("2026-01-01", periods=4)
    frame = pd.DataFrame(
        {
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "close": 10.0,
            "volume": 1.0,
        },
        index=calendar.delete(2),
    )
    codes = {issue.code for issue in validate_price_frame("A", frame, calendar)}
    assert "trading_day_gap" in codes


def test_adjustment_factor_jump_is_flagged() -> None:
    dates = pd.bdate_range("2026-01-01", periods=3)
    raw = pd.Series([10.0, 10.0, 10.0], index=dates)
    adjusted = pd.Series([10.0, 10.0, 20.0], index=dates)
    issues = detect_adjustment_jumps(raw, adjusted, "A")
    assert issues[0].code == "adjustment_factor_jump"
    assert issues[0].symbol == "A"
