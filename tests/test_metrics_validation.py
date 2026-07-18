from __future__ import annotations

import pandas as pd

from money_back.metrics import rolling_wealth_summary
from money_back.models import AcceptanceCriteria
from money_back.universe import DataGateResult
from money_back.validation import evaluate_acceptance


def test_rolling_three_year_multiple() -> None:
    dates = pd.bdate_range("2020-01-01", periods=800)
    equity = pd.Series(1.001 ** pd.RangeIndex(800), index=dates)
    summary = rolling_wealth_summary(pd.DataFrame({"equity": equity}), 756)
    assert summary["count"] == 44
    assert summary["median_multiple"] > 2.0


def test_failed_data_gate_overrides_performance_pass() -> None:
    metrics = {
        "median_multiple": 5.0,
        "p25_multiple": 3.0,
        "worst_multiple": 1.1,
        "max_drawdown": -0.2,
        "trade_days_per_year": 20.0,
        "capacity_evaluated": True,
        "liquidity_violation_days": 0,
    }
    gate = DataGateResult("FAIL", False, None, False, False, False, ())
    result = evaluate_acceptance(
        strategy_id="example",
        base_metrics=metrics,
        stress_metrics=metrics,
        data_gate=gate,
        criteria=AcceptanceCriteria(),
    )
    assert result["performance_passed"]
    assert result["status"] == "BLOCKED_DATA"


def test_missing_capacity_evidence_cannot_pass_performance_gate() -> None:
    metrics = {
        "median_multiple": 5.0,
        "p25_multiple": 3.0,
        "worst_multiple": 1.1,
        "max_drawdown": -0.2,
        "trade_days_per_year": 20.0,
        "capacity_evaluated": False,
        "liquidity_violation_days": 0,
    }
    gate = DataGateResult("PASS", True, "2013-01-01", True, True, True, ())
    result = evaluate_acceptance(
        strategy_id="example",
        base_metrics=metrics,
        stress_metrics=metrics,
        data_gate=gate,
        criteria=AcceptanceCriteria(),
    )
    assert not result["performance_passed"]
    assert result["status"] == "FAIL"
