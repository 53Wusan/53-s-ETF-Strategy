"""Frozen OHLCV-only sentiment index; no trading decisions.

v1.0.0 preserves the research formula on valid input. Invalid bars are rejected;
missing component scores remain missing instead of publishing stale values.
"""
from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pandas as pd


def rolling_rank(
    series: pd.Series, window: int, minimum: int | None = None
) -> pd.Series:
    min_periods = minimum or max(20, window // 2)

    def last_rank(values: np.ndarray) -> float:
        clean = values[np.isfinite(values)]
        if not len(clean) or not np.isfinite(values[-1]):
            return np.nan
        return float((clean <= values[-1]).sum() / len(clean) * 200 - 100)

    return series.rolling(window, min_periods=min_periods).apply(last_rank, raw=True)

def _adjusted_hlc(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    close = frame["adjusted_close"].astype(float)
    ratio = close / frame["close"].astype(float).replace(0, np.nan)
    return frame["high"] * ratio, frame["low"] * ratio, close

def stochastic(frame: pd.DataFrame, window: int) -> pd.Series:
    """Close location in the rolling adjusted high-low range, scaled -100..100."""
    high, low, close = _adjusted_hlc(frame)
    rolling_high = high.rolling(window, min_periods=window).max()
    rolling_low = low.rolling(window, min_periods=window).min()
    width = (rolling_high - rolling_low).replace(0, np.nan)
    return ((close - rolling_low) / width * 200 - 100).clip(-100, 100)

def rsi(close: pd.Series, window: int) -> pd.Series:
    """Wilder RSI scaled from 0..100 to -100..100."""
    delta = close.diff()
    gain = (
        delta.clip(lower=0)
        .ewm(alpha=1 / window, adjust=False, min_periods=window)
        .mean()
    )
    loss = (
        (-delta.clip(upper=0))
        .ewm(alpha=1 / window, adjust=False, min_periods=window)
        .mean()
    )
    relative_strength = gain / loss.replace(0, np.nan)
    return (2 * (100 - 100 / (1 + relative_strength)) - 100).clip(-100, 100)

def atr_percent(frame: pd.DataFrame, atr_window: int) -> pd.Series:
    high, low, close = _adjusted_hlc(frame)
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    return (
        true_range.ewm(
            alpha=1 / atr_window, adjust=False, min_periods=atr_window
        ).mean()
        / close
    )

CORE_SYMBOLS = ("TQQQ", "SOXL", "GDXU")
COMPONENTS = (
    "price_position",
    "momentum",
    "volume_flow",
    "volatility_state",
    "urgency",
)
INDEX_VERSION = "ohlcv-fg-v1.0.0"
FACTOR_WEIGHTS = MappingProxyType({
    "price_position": 0.30,
    "momentum": 0.20,
    "volume_flow": 0.25,
    "volatility_state": 0.10,
    "urgency": 0.15,
})
NONLINEAR_SCALE = 50.0
FEAR_ALPHA = 0.55
RECOVERY_ALPHA = 0.25


def _adjusted_ohlc(
    frame: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    close = frame["adjusted_close"].astype(float)
    adjustment = close / frame["close"].astype(float).replace(0, np.nan)
    return (
        frame["open"].astype(float) * adjustment,
        frame["high"].astype(float) * adjustment,
        frame["low"].astype(float) * adjustment,
        close,
    )


def _tanh_score(series: pd.Series, scale: pd.Series | float) -> pd.Series:
    return pd.Series(np.tanh((series / scale).to_numpy()) * 100, index=series.index)


def build_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Return five interpretable emotion components, each bounded -100..100."""
    required = ["open", "high", "low", "close", "adjusted_close", "volume"]
    if frame.index.has_duplicates or frame.index.hasnans:
        raise ValueError("Dates must be unique and non-missing")
    values = frame[required].astype(float)
    if not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
        raise ValueError("OHLCV must be finite and positive; missing or zero-volume rows block calculation")
    if ((values["high"] < values[["open", "close", "low"]].max(axis=1)) |
        (values["low"] > values[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC range")
    frame = values.sort_index().copy()
    open_, high, low, close = _adjusted_ohlc(frame)
    returns = close.pct_change(fill_method=None)
    daily_vol = returns.rolling(20, min_periods=15).std().replace(0, np.nan)
    result = pd.DataFrame(index=frame.index)

    price_rank = rolling_rank(close, 252, 126)
    result["price_position"] = pd.concat(
        [
            stochastic(frame, 21),
            stochastic(frame, 60),
            stochastic(frame, 252),
            price_rank,
        ],
        axis=1,
    ).mean(axis=1, skipna=False)

    macd = (
        close.ewm(span=12, adjust=False).mean()
        - close.ewm(span=26, adjust=False).mean()
    )
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_score = _tanh_score(macd - macd_signal, atr_percent(frame, 14) * close)
    result["momentum"] = pd.concat(
        [rsi(close, 6), rsi(close, 14), rsi(close, 21), macd_score], axis=1
    ).mean(axis=1, skipna=False)

    volume = frame["volume"].astype(float).replace(0, np.nan)
    close_location = ((2 * close - high - low) / (high - low).replace(0, np.nan)).clip(
        -1, 1
    )
    signed_volume = np.sign(returns).replace(0, np.nan).fillna(close_location) * volume
    volume_balance_5 = (
        signed_volume.rolling(5, min_periods=5).sum()
        / volume.rolling(5, min_periods=5).sum()
        * 100
    )
    volume_balance_20 = (
        signed_volume.rolling(20, min_periods=15).sum()
        / volume.rolling(20, min_periods=15).sum()
        * 100
    )
    chaikin_flow = (
        (close_location * volume).rolling(20, min_periods=15).sum()
        / volume.rolling(20, min_periods=15).sum()
        * 100
    )
    result["volume_flow"] = (
        pd.concat([volume_balance_5, volume_balance_20, chaikin_flow], axis=1)
        .mul([0.50, 0.30, 0.20], axis=1)
        .sum(axis=1, min_count=3)
    )

    atr = atr_percent(frame, 14)
    atr_rank = rolling_rank(atr, 252, 126)
    result["volatility_state"] = -atr_rank

    multi_horizon = pd.concat(
        [
            _tanh_score(
                close.pct_change(window, fill_method=None),
                daily_vol * np.sqrt(window),
            )
            for window in (3, 5, 10, 20)
        ],
        axis=1,
    ).mean(axis=1)
    drawdown_20 = close / close.rolling(20, min_periods=20).max() - 1
    drawdown_60 = close / close.rolling(60, min_periods=60).max() - 1
    drawdown_score = pd.concat(
        [
            (100 + 1000 * drawdown_20).clip(-100, 100),
            (100 + 500 * drawdown_60).clip(-100, 100),
        ],
        axis=1,
    ).mean(axis=1)
    gap = open_ / close.shift(1) - 1
    gap_score = _tanh_score(gap, daily_vol)
    result["urgency"] = pd.concat(
        [multi_horizon, drawdown_score, gap_score], axis=1
    ).mean(axis=1, skipna=False)
    return result.clip(-100, 100).replace([np.inf, -np.inf], np.nan)


def asymmetric_filter(series: pd.Series) -> pd.Series:
    """React quickly toward fear and require more evidence to recover."""
    values: list[float] = []
    previous = np.nan
    for value in series.to_numpy(dtype=float):
        if not np.isfinite(value):
            values.append(np.nan)
            continue
        if np.isnan(previous):
            previous = value
        else:
            alpha = FEAR_ALPHA if value < previous else RECOVERY_ALPHA
            previous = alpha * value + (1 - alpha) * previous
        values.append(previous)
    return pd.Series(values, index=series.index)


def score_index(features: pd.DataFrame) -> pd.DataFrame:
    result = features.copy()
    linear = sum(result[name] * weight for name, weight in FACTOR_WEIGHTS.items())
    result["score_raw"] = pd.Series(
        np.tanh((linear / NONLINEAR_SCALE).to_numpy()) * 100,
        index=result.index,
    )
    result["score"] = asymmetric_filter(result["score_raw"]).clip(-100, 100)
    return result

