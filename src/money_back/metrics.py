from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_wealth_multiples(backtest: pd.DataFrame, window: int = 756) -> pd.Series:
    return (backtest["equity"] / backtest["equity"].shift(window)).dropna()


def rolling_wealth_summary(backtest: pd.DataFrame, window: int = 756) -> dict[str, float]:
    multiple = rolling_wealth_multiples(backtest, window)
    if multiple.empty:
        return {
            "count": 0,
            "worst_multiple": np.nan,
            "p25_multiple": np.nan,
            "median_multiple": np.nan,
            "best_multiple": np.nan,
            "profitable_share": np.nan,
        }
    return {
        "count": int(len(multiple)),
        "worst_multiple": float(multiple.min()),
        "p25_multiple": float(multiple.quantile(0.25)),
        "median_multiple": float(multiple.median()),
        "best_multiple": float(multiple.max()),
        "profitable_share": float((multiple > 1.0).mean()),
    }


def longest_recovery_days(backtest: pd.DataFrame) -> int:
    underwater = backtest["drawdown"].lt(0.0)
    longest = current = 0
    for value in underwater.to_numpy(dtype=bool):
        current = current + 1 if value else 0
        longest = max(longest, current)
    return int(longest)


def annual_returns(backtest: pd.DataFrame) -> pd.Series:
    return backtest["equity"].resample("YE").last().pct_change().fillna(
        backtest["equity"].resample("YE").last() - 1.0
    )


def performance_metrics(backtest: pd.DataFrame) -> dict[str, float]:
    if backtest.empty:
        raise ValueError("Backtest is empty")
    periods = len(backtest)
    years = periods / 252.0
    ending = float(backtest["equity"].iloc[-1])
    daily_returns = backtest["net_return"].iloc[1:]
    daily_std = float(daily_returns.std(ddof=1))
    cagr = ending ** (1.0 / years) - 1.0 if years > 0 else np.nan
    max_drawdown = float(backtest["drawdown"].min())
    weight_columns = [column for column in backtest if column.startswith("w_")]
    concentration = (
        float(backtest[weight_columns].pow(2).sum(axis=1).mean()) if weight_columns else np.nan
    )
    trade_days = int(backtest["turnover"].gt(0.05).sum())
    participation = backtest.get(
        "max_order_participation", pd.Series(np.nan, index=backtest.index)
    )
    capacity_evaluated = bool(participation.notna().any())
    result = {
        "ending_equity": ending,
        "total_return": ending - 1.0,
        "cagr": cagr,
        "annual_volatility": daily_std * np.sqrt(252),
        "sharpe": float(daily_returns.mean() / daily_std * np.sqrt(252)) if daily_std > 0 else np.nan,
        "max_drawdown": max_drawdown,
        "calmar": cagr / abs(max_drawdown) if max_drawdown < 0 else np.nan,
        "total_turnover": float(backtest["turnover"].sum()),
        "annual_turnover": float(backtest["turnover"].sum() / years),
        "trade_days": trade_days,
        "trade_days_per_year": float(trade_days / years),
        "average_exposure": float(backtest["exposure"].mean()),
        "average_concentration_hhi": concentration,
        "longest_recovery_trading_days": longest_recovery_days(backtest),
        "unfilled_trade_days": int(backtest["unfilled_weight"].gt(0.001).sum()),
        "liquidity_violation_days": int(backtest["participation_violation"].sum()),
        "capacity_evaluated": capacity_evaluated,
        "maximum_order_participation": (
            float(participation.max()) if capacity_evaluated else np.nan
        ),
    }
    result.update(rolling_wealth_summary(backtest))
    return result
