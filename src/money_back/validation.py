from __future__ import annotations

from dataclasses import asdict

import numpy as np

from .models import AcceptanceCriteria
from .universe import DataGateResult


def neighbor_stability(
    baseline_median_multiple: float,
    neighbor_metrics: list[dict],
    criteria: AcceptanceCriteria,
) -> dict:
    threshold = baseline_median_multiple * criteria.stable_neighbor_fraction_of_baseline
    stable = [
        row["strategy_id"]
        for row in neighbor_metrics
        if np.isfinite(row.get("median_multiple", np.nan))
        and row["median_multiple"] >= threshold
    ]
    return {
        "threshold_multiple": threshold,
        "stable_count": len(stable),
        "required_count": criteria.stable_neighbor_count,
        "stable_strategies": stable,
        "passed": len(stable) >= criteria.stable_neighbor_count,
    }


def evaluate_acceptance(
    *,
    strategy_id: str,
    base_metrics: dict,
    stress_metrics: dict,
    data_gate: DataGateResult,
    criteria: AcceptanceCriteria,
    stability: dict | None = None,
) -> dict:
    checks = {
        "rolling_3y_median": base_metrics.get("median_multiple", np.nan)
        >= criteria.rolling_3y_median_multiple,
        "rolling_3y_p25": base_metrics.get("p25_multiple", np.nan)
        >= criteria.rolling_3y_p25_multiple,
        "rolling_3y_worst": base_metrics.get("worst_multiple", np.nan)
        >= criteria.rolling_3y_worst_multiple,
        "base_drawdown": abs(base_metrics.get("max_drawdown", -np.inf))
        <= criteria.base_max_drawdown,
        "stress_rolling_3y_median": stress_metrics.get("median_multiple", np.nan)
        >= criteria.stress_rolling_3y_median_multiple,
        "stress_drawdown": abs(stress_metrics.get("max_drawdown", -np.inf))
        <= criteria.stress_max_drawdown,
        "trade_frequency": base_metrics.get("trade_days_per_year", np.inf)
        <= criteria.maximum_trade_days_per_year,
        "capacity": bool(base_metrics.get("capacity_evaluated", False))
        and base_metrics.get("liquidity_violation_days", np.inf)
        <= criteria.maximum_liquidity_violation_days
        and bool(stress_metrics.get("capacity_evaluated", False))
        and stress_metrics.get("liquidity_violation_days", np.inf)
        <= criteria.maximum_liquidity_violation_days,
    }
    if stability is not None:
        checks["neighbor_stability"] = bool(stability["passed"])
    performance_passed = all(bool(value) for value in checks.values())
    status = "PASS" if performance_passed else "FAIL"
    if data_gate.status != "PASS":
        status = "BLOCKED_DATA"
    return {
        "strategy_id": strategy_id,
        "status": status,
        "performance_passed": performance_passed,
        "data_gate_passed": data_gate.status == "PASS",
        "checks": checks,
        "criteria": asdict(criteria),
        "stability": stability,
    }


def choose_candidate(results: list[dict]) -> dict:
    passed = [result for result in results if result["status"] == "PASS"]
    if not passed:
        return {
            "decision": "STOP",
            "selected_strategy": None,
            "reason": "No preregistered strategy passed both the data and performance gates.",
        }
    selected = max(passed, key=lambda row: row["base_metrics"]["median_multiple"])
    return {
        "decision": "PAPER_TRACK",
        "selected_strategy": selected["strategy_id"],
        "reason": "Highest rolling three-year median multiple among hard-gate passers.",
        "paper_tracking_weeks": 12,
    }
