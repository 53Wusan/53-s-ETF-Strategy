from __future__ import annotations

import numpy as np
import pandas as pd

FACTOR_WEIGHTS = {
    "market_position": 0.25,
    "etf_position": 0.25,
    "volatility": 0.25,
    "trend": 0.25,
}


def rolling_percentile(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    minimum = min_periods or max(20, window // 2)

    def rank_last(values: np.ndarray) -> float:
        clean = values[~np.isnan(values)]
        if len(clean) == 0:
            return np.nan
        return float((clean <= clean[-1]).sum() / len(clean))

    return series.rolling(window, min_periods=minimum).apply(rank_last, raw=True)


def to_score(percentile: pd.Series) -> pd.Series:
    return (percentile * 200 - 100).clip(-100, 100)


def _average_percentiles(series: pd.Series, windows: tuple[int, ...]) -> pd.Series:
    return pd.concat([rolling_percentile(series, window) for window in windows], axis=1).mean(axis=1)


def compute_factors(etf: pd.DataFrame, underlying: pd.DataFrame) -> pd.DataFrame:
    if etf.empty or underlying.empty:
        return pd.DataFrame()
    result = etf.copy().sort_index()
    adjustment = (result["adjusted_close"] / result["close"]).replace([np.inf, -np.inf], np.nan)
    result["execution_open"] = result["open"] * adjustment
    result["execution_close"] = result["adjusted_close"]
    underlying_close = underlying["adjusted_close"].reindex(result.index).ffill(limit=3)
    result["underlying_adjusted_close"] = underlying_close

    market_pct = _average_percentiles(underlying_close, (63, 126, 252))
    result["market_position"] = to_score(market_pct)

    etf_close = result["adjusted_close"]
    price_pct = _average_percentiles(etf_close, (63, 126, 252))
    drawdown = etf_close / etf_close.rolling(252, min_periods=63).max() - 1
    drawdown_pct = rolling_percentile(drawdown, 252, min_periods=63)
    result["etf_position"] = to_score(pd.concat([price_pct, drawdown_pct], axis=1).mean(axis=1))

    returns = etf_close.pct_change()
    realized_20 = returns.rolling(20, min_periods=15).std() * np.sqrt(252)
    realized_60 = returns.rolling(60, min_periods=30).std() * np.sqrt(252)
    previous_close = result["close"].shift(1)
    true_range = pd.concat(
        [
            result["high"] - result["low"],
            (result["high"] - previous_close).abs(),
            (result["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_ratio = true_range.rolling(20, min_periods=15).mean() / result["close"]
    volatility_pct = pd.concat(
        [
            rolling_percentile(realized_20, 252, min_periods=63),
            rolling_percentile(realized_60, 252, min_periods=63),
            rolling_percentile(atr_ratio, 252, min_periods=63),
        ],
        axis=1,
    ).mean(axis=1)
    result["volatility"] = to_score(1 - volatility_pct)

    trend_components: list[pd.Series] = []
    for span in (20, 60, 200):
        ema = etf_close.ewm(span=span, adjust=False, min_periods=max(10, span // 2)).mean()
        distance = etf_close / ema - 1
        slope = ema.pct_change(max(3, span // 10))
        trend_components.extend(
            [
                rolling_percentile(distance, 252, min_periods=63),
                rolling_percentile(slope, 252, min_periods=63),
            ]
        )
    result["trend"] = to_score(pd.concat(trend_components, axis=1).mean(axis=1))

    result["score"] = sum(result[name] * weight for name, weight in FACTOR_WEIGHTS.items()).clip(-100, 100)
    return result.dropna(subset=[*FACTOR_WEIGHTS, "score"])
