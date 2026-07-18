from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from money_back.backtest import simulate_portfolio
from money_back.metrics import performance_metrics
from money_back.models import ExecutionSpec
from money_back.strategies import build_targets, t5_spec


@pytest.mark.regression
def test_v0_1_frozen_metrics() -> None:
    fixture = Path(__file__).parent / "fixtures" / "t5_v0_1_prices.csv"
    data = pd.read_csv(fixture, parse_dates=["date"]).set_index("date")
    symbols = ["159516", "513120", "159206", "562500", "515880", "561380"]
    core_indices = ["上证指数", "深证成指", "创业板指", "科创50"]
    matrices = {
        field: pd.DataFrame(
            {symbol: data[f"etf_{symbol}_{field}"] for symbol in symbols}, index=data.index
        )
        for field in ["open", "close", "high", "low", "volume"]
    }
    index_close = pd.DataFrame(
        {label: data[f"index_{label}_close"] for label in core_indices}, index=data.index
    )
    targets, _, _ = build_targets(
        matrices["close"], index_close, matrices["close"].notna(), t5_spec()
    )
    backtest = simulate_portfolio(
        targets,
        matrices["open"], matrices["close"], matrices["high"], matrices["low"], matrices["volume"],
        start="2023-09-01", end="2026-07-08",
        execution=ExecutionSpec(execution="next_open", one_way_transaction_cost=0.001),
    )
    metrics = performance_metrics(backtest)
    assert metrics["ending_equity"] == pytest.approx(3.2294948130078933, abs=1e-12)
    assert metrics["max_drawdown"] == pytest.approx(-0.2127355762478581, abs=1e-12)
    assert metrics["trade_days_per_year"] == pytest.approx(31.959183673469386, abs=1e-12)
