from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

import pandas as pd

from .models import DailySignal, StrategySpec


def generate_daily_signal(
    *,
    spec: StrategySpec,
    targets: pd.DataFrame,
    scores: pd.DataFrame,
    gate: pd.Series,
    current_weights: dict[str, float] | None,
    universe: list[str],
    provenance: dict,
    warnings: list[str] | None = None,
    authorization: str = "research_only",
) -> DailySignal:
    date = targets.index[-1]
    target = targets.loc[date].fillna(0.0)
    current = pd.Series(current_weights or {}, dtype=float).reindex(target.index).fillna(0.0)
    ranking = scores.loc[date].dropna().sort_values(ascending=False)
    rankings = tuple(
        {
            "rank": rank,
            "symbol": str(symbol),
            "score": float(value),
            "eligible": str(symbol) in universe,
        }
        for rank, (symbol, value) in enumerate(ranking.items(), start=1)
    )
    orders = []
    for symbol in target.index:
        delta = float(target[symbol] - current[symbol])
        if abs(delta) <= 1e-9:
            continue
        orders.append(
            {
                "symbol": str(symbol),
                "action": "BUY" if delta > 0 else "SELL",
                "weight_change": delta,
                "target_weight": float(target[symbol]),
                "execution": "next_session_after_09_45_limit_or_twap",
            }
        )
    gate_open = bool(gate.reindex(targets.index).fillna(False).loc[date])
    reasons = [
        f"{spec.strategy_id} generated after the {date.date().isoformat()} close.",
        "Market gate is open." if gate_open else "Market gate is closed; target is cash.",
    ]
    return DailySignal(
        authorization=authorization,
        strategy_version=f"{spec.strategy_id}:{spec.version}",
        data_as_of=date.date().isoformat(),
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        market_gate_open=gate_open,
        universe_snapshot=tuple(universe),
        rankings=rankings,
        current_weights={str(key): float(value) for key, value in current.items()},
        target_weights={str(key): float(value) for key, value in target.items()},
        orders=tuple(orders),
        reasons=tuple(reasons),
        warnings=tuple(warnings or []),
        provenance=provenance,
    )


def signal_to_dict(signal: DailySignal) -> dict:
    return asdict(signal)

