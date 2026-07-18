from __future__ import annotations

import numpy as np
import pandas as pd

from .models import ExecutionSpec


def execution_price_matrix(
    raw_open: pd.DataFrame,
    raw_close: pd.DataFrame,
    raw_high: pd.DataFrame,
    raw_low: pd.DataFrame,
    execution: str,
) -> tuple[pd.DataFrame, int]:
    if execution in {"next_open", "next_open_delayed"}:
        return raw_open, 2 if execution == "next_open_delayed" else 1
    if execution == "next_close":
        return raw_close, 1
    if execution == "next_twap_proxy":
        return (raw_open + raw_high + raw_low + raw_close) / 4.0, 1
    if execution == "same_close":
        raise ValueError("Same-close execution is prohibited by the strict engine")
    raise ValueError(f"Unsupported execution mode: {execution}")


def _effective_weights(
    desired: np.ndarray,
    previous: np.ndarray,
    can_buy: np.ndarray,
    can_sell: np.ndarray,
) -> tuple[np.ndarray, float]:
    buying = desired > previous
    selling = desired < previous
    executable = (~buying | can_buy) & (~selling | can_sell)
    if executable.all():
        return desired.copy(), 0.0
    result = previous.copy()
    result[executable] = desired[executable]
    forced_weight = float(result[~executable].sum())
    available = max(0.0, 1.0 - forced_weight)
    executable_total = float(result[executable].sum())
    if executable_total > available and executable_total > 0:
        result[executable] *= available / executable_total
    unfilled = float(np.abs(desired - result).sum())
    return result, unfilled


def simulate_portfolio(
    targets: pd.DataFrame,
    raw_open: pd.DataFrame,
    raw_close: pd.DataFrame,
    raw_high: pd.DataFrame,
    raw_low: pd.DataFrame,
    raw_volume: pd.DataFrame,
    *,
    start: str,
    end: str,
    execution: ExecutionSpec,
    account_value: float = 2_000_000.0,
    median_turnover_amount_20d: pd.DataFrame | None = None,
    adjusted_open: pd.DataFrame | None = None,
    adjusted_close: pd.DataFrame | None = None,
    adjusted_high: pd.DataFrame | None = None,
    adjusted_low: pd.DataFrame | None = None,
) -> pd.DataFrame:
    raw_execution_prices, signal_delay = execution_price_matrix(
        raw_open, raw_close, raw_high, raw_low, execution.execution
    )
    return_execution_prices, return_delay = execution_price_matrix(
        adjusted_open if adjusted_open is not None else raw_open,
        adjusted_close if adjusted_close is not None else raw_close,
        adjusted_high if adjusted_high is not None else raw_high,
        adjusted_low if adjusted_low is not None else raw_low,
        execution.execution,
    )
    if return_delay != signal_delay:
        raise RuntimeError("Execution delay differs between raw and adjusted prices")
    desired_matrix = targets.shift(signal_delay).fillna(0.0)
    # Economic holding returns must come from an adjustment-consistent price
    # series. Raw prices remain authoritative for quote availability and daily
    # price-limit execution checks. This prevents distributions, unit splits,
    # or provider stitching from being recorded as portfolio losses.
    period_returns = (
        return_execution_prices.shift(-1) / return_execution_prices - 1.0
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    has_quote = (
        raw_execution_prices.notna()
        & raw_execution_prices.gt(0.0)
        & raw_volume.fillna(0.0).gt(0.0)
    )
    previous_close = raw_close.shift(1)
    one_price_day = (
        raw_open.eq(raw_high)
        & raw_open.eq(raw_low)
        & raw_open.eq(raw_close)
    )
    daily_move = raw_close / previous_close - 1.0
    locked_limit_up = one_price_day & daily_move.ge(0.095)
    locked_limit_down = one_price_day & daily_move.le(-0.095)
    can_buy_matrix = has_quote & ~locked_limit_up
    can_sell_matrix = has_quote & ~locked_limit_down
    dates = desired_matrix.index[
        (desired_matrix.index >= pd.Timestamp(start))
        & (desired_matrix.index <= pd.Timestamp(end))
    ]
    dates = dates[:-1]

    previous = np.zeros(len(targets.columns), dtype=float)
    equity = 1.0
    records: list[dict] = []
    for date in dates:
        desired = desired_matrix.loc[date].to_numpy(dtype=float)
        can_buy = can_buy_matrix.loc[date].to_numpy(dtype=bool)
        can_sell = can_sell_matrix.loc[date].to_numpy(dtype=bool)
        effective, unfilled = _effective_weights(desired, previous, can_buy, can_sell)
        blocked_buy = (desired > previous) & ~can_buy
        blocked_sell = (desired < previous) & ~can_sell
        turnover = float(np.abs(effective - previous).sum())
        cost = min(0.99, execution.one_way_transaction_cost * turnover)
        gross_return = float((effective * period_returns.loc[date].to_numpy(dtype=float)).sum())
        equity *= (1.0 - cost) * (1.0 + gross_return)
        participation_violation = False
        max_participation = np.nan
        if median_turnover_amount_20d is not None and date in median_turnover_amount_20d.index:
            amount = median_turnover_amount_20d.loc[date].to_numpy(dtype=float)
            order_notional = np.abs(effective - previous) * account_value * equity
            ratios = np.divide(
                order_notional,
                amount,
                out=np.full_like(order_notional, np.nan),
                where=np.isfinite(amount) & (amount > 0),
            )
            if np.isfinite(ratios).any():
                max_participation = float(np.nanmax(ratios))
                participation_violation = max_participation > 0.01
        record = {
            "date": date,
            "equity": equity,
            "gross_return": gross_return,
            "turnover": turnover,
            "cost": cost,
            "exposure": float(np.abs(effective).sum()),
            "unfilled_weight": unfilled,
            "blocked_buy_weight": float(np.abs(desired - effective)[blocked_buy].sum()),
            "blocked_sell_weight": float(np.abs(desired - effective)[blocked_sell].sum()),
            "limit_up_locked_orders": int((blocked_buy & locked_limit_up.loc[date].to_numpy(dtype=bool)).sum()),
            "limit_down_locked_orders": int((blocked_sell & locked_limit_down.loc[date].to_numpy(dtype=bool)).sum()),
            "participation_violation": participation_violation,
            "max_order_participation": max_participation,
        }
        record.update(
            {f"w_{symbol}": effective[position] for position, symbol in enumerate(targets.columns)}
        )
        records.append(record)
        previous = effective

    result = pd.DataFrame(records).set_index("date")
    result["drawdown"] = result["equity"] / result["equity"].cummax() - 1.0
    result["net_return"] = result["equity"].pct_change().fillna(result["equity"] - 1.0)
    return result
