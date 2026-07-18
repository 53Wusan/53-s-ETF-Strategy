from __future__ import annotations

import pandas as pd

from money_back.strategies import build_t5_targets, t5_spec


def test_t5_replacement_requires_strictly_more_than_buffer() -> None:
    dates = pd.bdate_range("2026-01-01", periods=5)
    close = pd.DataFrame(
        {
            "A": [100.0, 110.0, 121.0, 133.1, 146.41],
            "B": [100.0, 108.0, 119.88, 134.14572, 152.92612],
        },
        index=dates,
    )
    indices = pd.DataFrame({name: [100, 101, 102, 103, 104] for name in ["上证", "深证", "创业", "科创"]}, index=dates)
    eligibility = pd.DataFrame(True, index=dates, columns=close.columns)
    spec = t5_spec(momentum_window=1, top_k=1, replacement_buffer=0.02, market_gate_window=1)
    targets, _, _ = build_t5_targets(close, indices, eligibility, spec)
    assert targets.loc[dates[2], "A"] == 1.0
    assert targets.loc[dates[3], "A"] == 1.0
    assert targets.loc[dates[4], "B"] == 1.0


def test_market_gate_closes_when_no_index_is_positive() -> None:
    dates = pd.bdate_range("2026-01-01", periods=4)
    close = pd.DataFrame({"A": [100, 101, 102, 103]}, index=dates)
    indices = pd.DataFrame({name: [100, 99, 98, 97] for name in ["上证", "深证", "创业", "科创"]}, index=dates)
    eligibility = pd.DataFrame(True, index=dates, columns=close.columns)
    targets, _, gate = build_t5_targets(
        close,
        indices,
        eligibility,
        t5_spec(momentum_window=1, market_gate_window=1),
    )
    assert not bool(gate.iloc[-1])
    assert targets.iloc[-1].sum() == 0.0
