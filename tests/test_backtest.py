from __future__ import annotations

import pandas as pd
import pytest

from money_back.backtest import simulate_portfolio
from money_back.models import ExecutionSpec


def _prices() -> tuple[pd.DataFrame, ...]:
    dates = pd.bdate_range("2026-01-01", periods=5)
    price = pd.DataFrame({"A": [100, 101, 102, 103, 104], "B": [100, 100, 100, 100, 100]}, index=dates)
    volume = pd.DataFrame(1000.0, index=dates, columns=price.columns)
    return price, price, price, price, volume


def test_same_close_is_rejected() -> None:
    price, close, high, low, volume = _prices()
    targets = pd.DataFrame(0.0, index=price.index, columns=price.columns)
    with pytest.raises(ValueError, match="Same-close"):
        simulate_portfolio(
            targets, price, close, high, low, volume,
            start="2026-01-01", end="2026-01-07",
            execution=ExecutionSpec(execution="same_close"),
        )


def test_untradable_asset_preserves_previous_weight() -> None:
    price, close, high, low, volume = _prices()
    targets = pd.DataFrame(
        {"A": [1.0, 0.0, 0.0, 0.0, 0.0], "B": [0.0, 1.0, 1.0, 1.0, 1.0]},
        index=price.index,
    )
    volume.loc[price.index[2], "A"] = 0.0
    result = simulate_portfolio(
        targets, price, close, high, low, volume,
        start="2026-01-01", end="2026-01-07",
        execution=ExecutionSpec(execution="next_open", one_way_transaction_cost=0.0),
    )
    assert result.loc[price.index[2], "w_A"] == 1.0
    assert result.loc[price.index[2], "unfilled_weight"] > 0.0


def test_transaction_cost_reduces_equity() -> None:
    price, close, high, low, volume = _prices()
    targets = pd.DataFrame({"A": 1.0, "B": 0.0}, index=price.index)
    no_cost = simulate_portfolio(
        targets, price, close, high, low, volume,
        start="2026-01-01", end="2026-01-07",
        execution=ExecutionSpec(execution="next_open", one_way_transaction_cost=0.0),
    )
    with_cost = simulate_portfolio(
        targets, price, close, high, low, volume,
        start="2026-01-01", end="2026-01-07",
        execution=ExecutionSpec(execution="next_open", one_way_transaction_cost=0.001),
    )
    assert with_cost["equity"].iloc[-1] < no_cost["equity"].iloc[-1]


def test_locked_price_limits_block_only_the_prohibited_direction() -> None:
    dates = pd.bdate_range("2026-01-01", periods=6)
    open_price = pd.DataFrame(
        {"A": [100.0, 100.0, 110.0, 110.0, 99.0, 99.0]}, index=dates
    )
    close = open_price.copy()
    high = open_price.copy()
    low = open_price.copy()
    volume = pd.DataFrame(1000.0, index=dates, columns=["A"])
    targets = pd.DataFrame({"A": [0.0, 1.0, 1.0, 0.0, 0.0, 0.0]}, index=dates)

    result = simulate_portfolio(
        targets,
        open_price,
        close,
        high,
        low,
        volume,
        start="2026-01-01",
        end="2026-01-08",
        execution=ExecutionSpec(execution="next_open", one_way_transaction_cost=0.0),
    )

    # The day after the buy signal is a locked +10% day, so the order remains cash.
    assert result.loc[dates[2], "w_A"] == 0.0
    assert result.loc[dates[2], "limit_up_locked_orders"] == 1
    # The buy can execute on the following normal day.
    assert result.loc[dates[3], "w_A"] == 1.0
    # The day after the sell signal is a locked -10% day, so the holding is preserved.
    assert result.loc[dates[4], "w_A"] == 1.0
    assert result.loc[dates[4], "limit_down_locked_orders"] == 1


def test_order_participation_above_one_percent_is_flagged() -> None:
    price, close, high, low, volume = _prices()
    targets = pd.DataFrame({"A": 1.0, "B": 0.0}, index=price.index)
    median_amount = pd.DataFrame(
        100_000_000.0, index=price.index, columns=price.columns
    )
    result = simulate_portfolio(
        targets,
        price,
        close,
        high,
        low,
        volume,
        start="2026-01-01",
        end="2026-01-07",
        execution=ExecutionSpec(execution="next_open", one_way_transaction_cost=0.0),
        account_value=2_000_000.0,
        median_turnover_amount_20d=median_amount,
    )
    assert bool(result["participation_violation"].iloc[1])
    assert result["max_order_participation"].iloc[1] > 0.01


def test_adjusted_returns_ignore_raw_distribution_or_unit_split() -> None:
    dates = pd.bdate_range("2026-01-01", periods=5)
    raw = pd.DataFrame({"A": [100.0, 102.0, 51.0, 52.0, 53.0]}, index=dates)
    adjusted = pd.DataFrame({"A": [100.0, 102.0, 102.0, 104.0, 106.0]}, index=dates)
    volume = pd.DataFrame(1000.0, index=dates, columns=["A"])
    targets = pd.DataFrame({"A": 1.0}, index=dates)

    result = simulate_portfolio(
        targets,
        raw,
        raw,
        raw,
        raw,
        volume,
        start="2026-01-01",
        end="2026-01-07",
        execution=ExecutionSpec(execution="next_open", one_way_transaction_cost=0.0),
        adjusted_open=adjusted,
        adjusted_close=adjusted,
        adjusted_high=adjusted,
        adjusted_low=adjusted,
    )

    # The raw 102 -> 51 discontinuity is a non-economic 2-for-1 scale change.
    assert result["gross_return"].min() >= 0.0
    assert result["equity"].iloc[-1] > 1.0
