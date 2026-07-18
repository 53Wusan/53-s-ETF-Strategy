from __future__ import annotations

import hashlib
import json
import math
import numbers
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UniverseRules:
    asset_types: tuple[str, ...] = ("equity_etf",)
    minimum_listing_days: int = 120
    minimum_median_amount_20d: float = 100_000_000.0
    maximum_order_participation: float = 0.01
    account_value: float = 2_000_000.0
    exclude_cross_border: bool = True
    exclude_bond: bool = True
    exclude_commodity: bool = True
    exclude_money_market: bool = True
    exclude_leveraged_inverse: bool = True
    deduplicate_tracked_index: bool = True


@dataclass(frozen=True)
class ExecutionSpec:
    signal_time: str = "close_t"
    execution: str = "next_twap_proxy"
    one_way_transaction_cost: float = 0.001
    stress_transaction_cost: float = 0.002
    timezone: str = "Asia/Shanghai"
    reject_same_close: bool = True


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    family: str
    version: str = "0.2"
    momentum_window: int | None = None
    secondary_momentum_window: int | None = None
    top_k: int = 2
    replacement_buffer: float = 0.02
    market_gate_window: int = 60
    minimum_positive_indices: int = 1
    rebalance_frequency: str = "daily"
    weighting: str = "equal"
    absolute_momentum_required: bool = False
    trend_window: int | None = None
    volatility_window: int = 20
    volatility_target: float | None = None
    maximum_asset_weight: float = 1.0
    universe_rules: UniverseRules = field(default_factory=UniverseRules)
    execution_rules: ExecutionSpec = field(default_factory=ExecutionSpec)
    data_version: str = "fixed-pool-free-v0.2"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcceptanceCriteria:
    rolling_3y_median_multiple: float = 4.0
    rolling_3y_p25_multiple: float = 2.0
    rolling_3y_worst_multiple: float = 1.0
    base_max_drawdown: float = 0.40
    stress_rolling_3y_median_multiple: float = 3.0
    stress_max_drawdown: float = 0.50
    maximum_trade_days_per_year: float = 60.0
    maximum_liquidity_violation_days: int = 0
    stable_neighbor_count: int = 6
    stable_neighbor_fraction_of_baseline: float = 0.70


@dataclass(frozen=True)
class DataIssue:
    code: str
    severity: str
    message: str
    symbol: str | None = None
    date: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def canonical_json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_safe(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        numeric = float(value)
        return None if not math.isfinite(numeric) else numeric
    return value


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    created_at: str
    strategy: dict[str, Any]
    execution: dict[str, Any]
    universe: dict[str, Any]
    data_start: str
    data_end: str
    data_sources: tuple[dict[str, Any], ...]
    config_hash: str
    code_commit: str
    metrics: dict[str, Any]
    data_gate: dict[str, Any]
    acceptance: dict[str, Any]
    warnings: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        strategy: StrategySpec,
        execution: ExecutionSpec,
        universe: UniverseRules,
        data_start: str,
        data_end: str,
        data_sources: list[dict[str, Any]],
        code_commit: str,
        metrics: dict[str, Any],
        data_gate: dict[str, Any],
        acceptance: dict[str, Any],
        warnings: list[str] | None = None,
    ) -> "RunManifest":
        config = {
            "strategy": asdict(strategy),
            "execution": asdict(execution),
            "universe": asdict(universe),
        }
        return cls(
            run_id=run_id,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            strategy=asdict(strategy),
            execution=asdict(execution),
            universe=asdict(universe),
            data_start=data_start,
            data_end=data_end,
            data_sources=tuple(data_sources),
            config_hash=stable_hash(config),
            code_commit=code_commit,
            metrics=metrics,
            data_gate=data_gate,
            acceptance=acceptance,
            warnings=tuple(warnings or []),
        )


@dataclass(frozen=True)
class DailySignal:
    authorization: str
    strategy_version: str
    data_as_of: str
    generated_at: str
    market_gate_open: bool
    universe_snapshot: tuple[str, ...]
    rankings: tuple[dict[str, Any], ...]
    current_weights: dict[str, float]
    target_weights: dict[str, float]
    orders: tuple[dict[str, Any], ...]
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance: dict[str, Any]


def write_immutable_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json_safe(value)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"Immutable artifact already exists with different content: {target}")
        return target
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return target
