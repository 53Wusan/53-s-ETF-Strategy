import numpy as np
import pandas as pd
import pytest

from app.services.execution_research import CapitalPolicy, ExecutionRule, simulate
from app.services.shadow_account import calculate
from dataclasses import asdict


def test_deployment_account_starts_empty_and_does_not_book_future_plan():
    dates = pd.bdate_range("2026-09-28", "2026-10-02")
    data = {"dates": dates, "symbols": ("TQQQ",), "open": np.full((5, 1), 100.),
            "close": np.full((5, 1), 100.), "score": np.full((5, 1), -10.)}
    config = {"activation_date": "2026-10-05", "initial_usd": 60000,
              "rule": asdict(ExecutionRule(buy_score=0))}
    result = calculate(config, data)
    assert result["trades"] == []
    assert result["positions"] == {}
    assert result["cash_usd"] == 60000
    plan = result["next_open_plan"]
    assert plan["next_open_date"] == "2026-10-05"
    assert plan["actions"][0]["gross_hkd"] / 7.8 == pytest.approx(3000 / 1.001)


def test_new_capital_scales_account_without_importing_old_reserve():
    data = {"dates": pd.bdate_range("2026-10-01", periods=3), "symbols": ("TQQQ",),
            "open": np.full((3, 1), 100.), "close": np.full((3, 1), 100.),
            "score": np.full((3, 1), -10.)}
    result = simulate(data, ExecutionRule(buy_score=0), start="2026-10-02", detail=True,
                      capital=CapitalPolicy(initial_usd=60000, reserve_hkd=0))
    assert result["daily"][0]["cash_hkd"] / 7.8 == pytest.approx(57000)
