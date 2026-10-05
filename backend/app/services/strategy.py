from __future__ import annotations

from dataclasses import dataclass

from app.models import SignalAction


@dataclass(frozen=True)
class Thresholds:
    buys: tuple[float, float, float] = (-60.0, -75.0, -90.0)
    sells: tuple[float, float, float] = (60.0, 75.0, 90.0)


@dataclass
class State:
    position_steps: int = 0
    buy_mask: int = 0
    sell_mask: int = 0


@dataclass(frozen=True)
class Decision:
    action: SignalAction
    delta: int
    reason: str


def decide(prev_score: float, score: float, thresholds: Thresholds, state: State) -> Decision:
    buy_hits: list[int] = []
    for index, level in enumerate(thresholds.buys):
        bit = 1 << index
        if prev_score > level >= score and not state.buy_mask & bit:
            buy_hits.append(index)
    available = max(0, 3 - state.position_steps)
    buy_count = min(len(buy_hits), available)
    if buy_count:
        for index in buy_hits[:buy_count]:
            state.buy_mask |= 1 << index
        state.position_steps += buy_count
        action = SignalAction.BUY if state.position_steps == buy_count else SignalAction.ADD
        return Decision(action, buy_count, f"向下穿越 {buy_count} 档恐惧阈值")

    sell_hits: list[int] = []
    for index, level in enumerate(thresholds.sells):
        bit = 1 << index
        if prev_score < level <= score and not state.sell_mask & bit:
            sell_hits.append(index)
    sell_count = min(len(sell_hits), state.position_steps)
    if sell_count:
        for index in sell_hits[:sell_count]:
            state.sell_mask |= 1 << index
        state.position_steps -= sell_count
        action = SignalAction.EXIT if state.position_steps == 0 else SignalAction.REDUCE
        if state.position_steps == 0:
            state.buy_mask = 0
            state.sell_mask = 0
        return Decision(action, -sell_count, f"向上穿越 {sell_count} 档贪婪阈值")
    return Decision(SignalAction.HOLD, 0, "未穿越新的交易阈值")

