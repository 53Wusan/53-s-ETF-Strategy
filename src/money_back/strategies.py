from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .models import StrategySpec


def t5_spec(strategy_id: str = "t5_v0_2_baseline", **overrides) -> StrategySpec:
    spec = StrategySpec(
        strategy_id=strategy_id,
        family="t5",
        momentum_window=15,
        top_k=2,
        replacement_buffer=0.02,
        market_gate_window=60,
        minimum_positive_indices=1,
        rebalance_frequency="daily",
        weighting="equal",
    )
    return replace(spec, **overrides) if overrides else spec


def preregistered_specs() -> list[StrategySpec]:
    baseline = t5_spec()
    neighbors = [
        replace(baseline, strategy_id="t5_neighbor_10d", momentum_window=10),
        replace(baseline, strategy_id="t5_neighbor_20d", momentum_window=20),
        replace(baseline, strategy_id="t5_neighbor_0p", replacement_buffer=0.0),
        replace(baseline, strategy_id="t5_neighbor_4p", replacement_buffer=0.04),
        replace(baseline, strategy_id="t5_neighbor_top1", top_k=1),
        replace(baseline, strategy_id="t5_neighbor_top3", top_k=3),
        replace(baseline, strategy_id="t5_neighbor_40i1", market_gate_window=40),
        replace(baseline, strategy_id="t5_neighbor_120i1", market_gate_window=120),
        replace(baseline, strategy_id="t5_neighbor_60i2", minimum_positive_indices=2),
    ]
    volatility_control = replace(
        baseline,
        strategy_id="t5_volatility_control_30",
        volatility_target=0.30,
        notes=("20-day realized portfolio volatility; exposure floored to 25% steps",),
    )
    dual_momentum = StrategySpec(
        strategy_id="challenger_a_dual_momentum",
        family="dual_momentum",
        momentum_window=63,
        secondary_momentum_window=126,
        top_k=2,
        rebalance_frequency="weekly",
        weighting="equal",
        absolute_momentum_required=True,
    )
    volatility_trend = StrategySpec(
        strategy_id="challenger_b_vol_adjusted_trend",
        family="volatility_adjusted_trend",
        momentum_window=63,
        top_k=2,
        rebalance_frequency="weekly",
        weighting="inverse_volatility",
        absolute_momentum_required=True,
        trend_window=200,
        volatility_window=20,
        maximum_asset_weight=0.60,
    )
    return [baseline, *neighbors, volatility_control, dual_momentum, volatility_trend]


def market_gate(
    index_close: pd.DataFrame,
    window: int,
    minimum_positive_indices: int,
) -> tuple[pd.Series, pd.DataFrame]:
    momentum = index_close / index_close.shift(window) - 1.0
    gate = (momentum > 0).sum(axis=1) >= minimum_positive_indices
    return gate.fillna(False), momentum


def _t5_weights_from_scores(
    scores: pd.DataFrame,
    gate: pd.Series,
    eligibility: pd.DataFrame,
    *,
    top_k: int,
    replacement_buffer: float,
) -> pd.DataFrame:
    target_values = np.zeros(scores.shape, dtype=float)
    score_values = scores.to_numpy(dtype=float)
    gate_values = gate.reindex(scores.index).fillna(False).to_numpy(dtype=bool)
    eligible_values = eligibility.reindex_like(scores).fillna(False).to_numpy(dtype=bool)
    held: list[int] = []
    for row_position in range(len(scores.index)):
        row_scores = score_values[row_position]
        valid_positions = np.flatnonzero(~np.isnan(row_scores) & eligible_values[row_position])
        if not gate_values[row_position] or valid_positions.size == 0:
            held = []
            continue
        ordered = valid_positions[np.argsort(row_scores[valid_positions])[::-1]].tolist()
        valid_set = set(valid_positions.tolist())
        held = [position for position in held if position in valid_set]
        desired_count = min(top_k, len(ordered))
        while len(held) < desired_count:
            held.append(next(position for position in ordered if position not in held))
        changed = True
        while changed and held:
            changed = False
            outside = [position for position in ordered if position not in held]
            if not outside:
                break
            weakest = min(held, key=lambda position: row_scores[position])
            challenger = outside[0]
            if row_scores[challenger] > row_scores[weakest] + replacement_buffer:
                held.remove(weakest)
                held.append(challenger)
                changed = True
        for column_position in held:
            target_values[row_position, column_position] = 1.0 / len(held)
    return pd.DataFrame(target_values, index=scores.index, columns=scores.columns)


def build_t5_targets(
    adjusted_close: pd.DataFrame,
    index_close: pd.DataFrame,
    eligibility: pd.DataFrame,
    spec: StrategySpec,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    if spec.momentum_window is None:
        raise ValueError("T5 requires momentum_window")
    scores = adjusted_close / adjusted_close.shift(spec.momentum_window) - 1.0
    gate, _ = market_gate(
        index_close, spec.market_gate_window, spec.minimum_positive_indices
    )
    targets = _t5_weights_from_scores(
        scores,
        gate,
        eligibility,
        top_k=spec.top_k,
        replacement_buffer=spec.replacement_buffer,
    )
    return targets, scores, gate


def apply_volatility_control(
    base_targets: pd.DataFrame,
    adjusted_close: pd.DataFrame,
    *,
    target_volatility: float = 0.30,
    lookback: int = 20,
    step: float = 0.25,
) -> tuple[pd.DataFrame, pd.Series]:
    asset_returns = adjusted_close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    portfolio_returns = (base_targets.shift(1) * asset_returns).sum(axis=1, min_count=1)
    realized = portfolio_returns.rolling(lookback, min_periods=lookback).std(ddof=1) * np.sqrt(252)
    raw = (target_volatility / realized.replace(0.0, np.nan)).clip(lower=0.0, upper=1.0)
    exposure = (np.floor(raw / step) * step).clip(lower=0.0, upper=1.0).fillna(0.0)
    return base_targets.mul(exposure, axis=0), exposure


def _weekly_evaluation_mask(index: pd.DatetimeIndex) -> pd.Series:
    periods = index.to_period("W-FRI")
    next_period = pd.Series(periods, index=index).shift(-1)
    return pd.Series(periods != next_period.to_numpy(), index=index).fillna(True)


def _carry_weekly_targets(candidate: pd.DataFrame, evaluation_mask: pd.Series) -> pd.DataFrame:
    weekly = candidate.where(evaluation_mask, np.nan, axis=0)
    return weekly.ffill().fillna(0.0)


def build_dual_momentum_targets(
    adjusted_close: pd.DataFrame,
    eligibility: pd.DataFrame,
    spec: StrategySpec,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    if spec.momentum_window is None or spec.secondary_momentum_window is None:
        raise ValueError("Dual momentum requires two windows")
    fast = adjusted_close / adjusted_close.shift(spec.momentum_window) - 1.0
    slow = adjusted_close / adjusted_close.shift(spec.secondary_momentum_window) - 1.0
    scores = (fast + slow) / 2.0
    eligible = eligibility & fast.gt(0.0) & slow.gt(0.0)
    candidate = pd.DataFrame(0.0, index=adjusted_close.index, columns=adjusted_close.columns)
    for date in adjusted_close.index:
        valid = scores.loc[date].where(eligible.loc[date]).dropna().nlargest(spec.top_k)
        if not valid.empty:
            candidate.loc[date, valid.index] = 1.0 / len(valid)
    evaluation = _weekly_evaluation_mask(adjusted_close.index)
    targets = _carry_weekly_targets(candidate, evaluation)
    gate = targets.sum(axis=1).gt(0.0)
    return targets, scores, gate


def _capped_inverse_vol_weights(volatility: pd.Series, maximum_weight: float) -> pd.Series:
    inverse = 1.0 / volatility.replace(0.0, np.nan)
    inverse = inverse.replace([np.inf, -np.inf], np.nan).dropna()
    if inverse.empty:
        return inverse
    weights = inverse / inverse.sum()
    if len(weights) == 1:
        return weights.clip(upper=maximum_weight)
    if len(weights) == 2 and weights.max() > maximum_weight:
        largest = weights.idxmax()
        smallest = weights.idxmin()
        weights.loc[largest] = maximum_weight
        weights.loc[smallest] = 1.0 - maximum_weight
    return weights


def build_volatility_trend_targets(
    adjusted_close: pd.DataFrame,
    eligibility: pd.DataFrame,
    spec: StrategySpec,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    if spec.momentum_window is None or spec.trend_window is None:
        raise ValueError("Volatility trend requires momentum and trend windows")
    returns = adjusted_close.pct_change(fill_method=None)
    momentum = adjusted_close / adjusted_close.shift(spec.momentum_window) - 1.0
    volatility = returns.rolling(spec.volatility_window, min_periods=spec.volatility_window).std(ddof=1) * np.sqrt(252)
    trend = adjusted_close > adjusted_close.rolling(spec.trend_window, min_periods=spec.trend_window).mean()
    scores = momentum / volatility.replace(0.0, np.nan)
    eligible = eligibility & momentum.gt(0.0) & trend
    candidate = pd.DataFrame(0.0, index=adjusted_close.index, columns=adjusted_close.columns)
    for date in adjusted_close.index:
        valid_scores = scores.loc[date].where(eligible.loc[date]).dropna().nlargest(spec.top_k)
        if valid_scores.empty:
            continue
        weights = _capped_inverse_vol_weights(
            volatility.loc[date, valid_scores.index], spec.maximum_asset_weight
        )
        candidate.loc[date, weights.index] = weights
    evaluation = _weekly_evaluation_mask(adjusted_close.index)
    targets = _carry_weekly_targets(candidate, evaluation)
    gate = targets.sum(axis=1).gt(0.0)
    return targets, scores, gate


def build_targets(
    adjusted_close: pd.DataFrame,
    index_close: pd.DataFrame,
    eligibility: pd.DataFrame,
    spec: StrategySpec,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    if spec.family == "t5":
        targets, scores, gate = build_t5_targets(
            adjusted_close, index_close, eligibility, spec
        )
        if spec.volatility_target is not None:
            targets, _ = apply_volatility_control(
                targets,
                adjusted_close,
                target_volatility=spec.volatility_target,
                lookback=spec.volatility_window,
            )
        return targets, scores, gate
    if spec.family == "dual_momentum":
        return build_dual_momentum_targets(adjusted_close, eligibility, spec)
    if spec.family == "volatility_adjusted_trend":
        return build_volatility_trend_targets(adjusted_close, eligibility, spec)
    raise ValueError(f"Unsupported strategy family: {spec.family}")
