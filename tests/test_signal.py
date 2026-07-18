from __future__ import annotations

import pandas as pd

from money_back.signal import generate_daily_signal
from money_back.strategies import t5_spec


def test_daily_signal_is_research_only_and_auditable() -> None:
    dates = pd.bdate_range("2026-01-01", periods=2)
    targets = pd.DataFrame({"A": [0.0, 1.0], "B": [0.0, 0.0]}, index=dates)
    scores = pd.DataFrame({"A": [0.1, 0.2], "B": [0.0, 0.1]}, index=dates)
    gate = pd.Series([False, True], index=dates)
    signal = generate_daily_signal(
        spec=t5_spec(),
        targets=targets,
        scores=scores,
        gate=gate,
        current_weights={"A": 0.0, "B": 0.0},
        universe=["A", "B"],
        provenance={"run": "fixture"},
        warnings=["fixture"],
    )
    assert signal.authorization == "research_only"
    assert signal.market_gate_open
    assert signal.orders[0]["action"] == "BUY"
    assert signal.provenance["run"] == "fixture"

