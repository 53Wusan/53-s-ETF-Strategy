"""Causal, cash-constrained research of executable 5% lots using raw FG scores."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.research_cockpit import (
    DEFAULT_SYMBOLS,
    INPUT_SYMBOLS,
    _active_data,
    _research_output,
    input_frame,
)

FX = 7.8  # Declared fixed reporting assumption, not a live conversion quote.
INITIAL_HKD = 500_000.0
INITIAL = INITIAL_HKD / FX
RESERVE = 120_000.0 / FX
OUT_NAME = "execution_v2"
PROFILE_IDS = ("near_best", "best", "rank2", "rank3", "short", "balanced")


def indicator_scale() -> dict:
    """Bound the frozen model using its clipped features and convex smoothing."""
    config = _research_output().parents[1] / "research/configs/no_yinn_paper_v1.json"
    parameters = json.loads(config.read_text(encoding="utf-8"))["indicator_parameters"]
    bias, weights, memory = parameters[0], parameters[1:4], parameters[4]
    if not 0 <= memory < 1:
        raise ValueError("平滑参数不满足凸组合范围")
    amplitude = sum(abs(weight) for weight in weights)
    # Include the zero initial latent state; smoothing cannot leave this hull.
    lower, upper = min(0, bias - amplitude), max(0, bias + amplitude)
    return {
        "attainable_min": float(np.clip(100 * np.tanh(lower), -99, 99)),
        "attainable_max": float(np.clip(100 * np.tanh(upper), -99, 99)),
        "smoothing_memory": memory,
        "parameters": parameters,
        "display_min": -50,
        "display_max": 50,
        "description": "21日价格位置与RSI14自身252日分位加权，再平滑并压缩；原始分数不等于历史百分位。",
    }


@dataclass(frozen=True)
class ExecutionRule:
    buy_score: int = -20
    add_drop: float = 0.10
    buy_gap_days: int = 7
    sell_score: int = 40
    profit_target: float = 0.30
    max_hold_days: int = 60
    sell_gap_days: int = 3
    reentry_days: int = 7
    exit_mode: str = "score_or_profit"
    trailing_drop: float = 0.10
    fee_rate: float = 0.001
    stop_loss: float | None = None
    idle_exit_days: int | None = None
    idle_exit_band: float = 0.05


def load_arrays() -> dict:
    frames = {s: input_frame(s) for s in DEFAULT_SYMBOLS}
    dates = pd.DatetimeIndex(sorted(set.intersection(*(set(f.index) for f in frames.values()))))
    data = {"dates": dates, "symbols": tuple(DEFAULT_SYMBOLS)}
    for name, col in (("open", "open"), ("close", "close"), ("score", "without_long")):
        data[name] = np.column_stack(
            [frames[s].reindex(dates)[col].to_numpy(float) for s in DEFAULT_SYMBOLS]
        )
    if not np.isfinite(data["open"]).all() or not np.isfinite(data["close"]).all():
        raise ValueError("共同行情存在无效价格")
    return data


@dataclass(frozen=True)
class CapitalPolicy:
    """Research sizing; fractions refer to original account capital, fees included."""

    lot_fraction: float = 0.05
    max_lots: int = 4
    reserve_hkd: float = 120_000.0
    max_symbols: int = 5
    initial_usd: float = INITIAL

    def __post_init__(self):
        if (
            not np.isfinite(self.lot_fraction)
            or not 0 < self.lot_fraction <= 1
            or not isinstance(self.max_lots, int)
            or self.max_lots < 1
            or self.lot_fraction * self.max_lots > 1 + 1e-9
            or not np.isfinite(self.reserve_hkd)
            or not np.isfinite(self.initial_usd)
            or self.initial_usd <= 0
            or not 0 <= self.reserve_hkd <= self.initial_usd * FX
            or not isinstance(self.max_symbols, int)
            or self.max_symbols < 1
        ):
            raise ValueError("仓位参数无效")


def simulate(
    data: dict,
    rule: ExecutionRule,
    start: str = "2024-01-02",
    end: str | None = None,
    detail: bool = False,
    *,
    capital: CapitalPolicy | None = None,
) -> dict:
    sizing = capital or CapitalPolicy()
    dates, opening, closing, scores = (data[k] for k in ("dates", "open", "close", "score"))
    symbols = data["symbols"]
    ids = np.flatnonzero((dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end or dates[-1])))
    if not len(ids) or ids[0] == 0 or not np.isfinite(scores[ids[0] - 1 : ids[-1] + 1]).all():
        raise ValueError("所选区间没有完整的前收盘贪恐指数")
    # Optional causal, per-symbol gates are used by percentile research only.
    # Published fixed-score profiles continue to use the unchanged scalar rule.
    for key in ("buy_threshold", "sell_threshold", "buy_priority"):
        if key in data and (
            data[key].shape != scores.shape
            or not np.isfinite(data[key][ids[0] - 1 : ids[-1] + 1]).all()
        ):
            raise ValueError("分位阈值缺少完整的前收盘历史")
    if "buy_allowed" in data and (
        data["buy_allowed"].shape != (len(dates),) or data["buy_allowed"].dtype != np.bool_
    ):
        raise ValueError("买入许可必须是逐日布尔状态")
    n = len(symbols)
    initial = sizing.initial_usd
    initial_hkd = initial * FX
    cash = initial
    shares, basis = np.zeros(n), np.zeros(n)
    lots: list[list[tuple[float, float, pd.Timestamp]]] = [[] for _ in symbols]
    first, last_buy_date, last_sell_date, flat_date, last_action = ([None] * n for _ in range(5))
    last_buy = np.full(n, np.nan)
    peak_price = np.zeros(n)
    selling, armed = np.zeros(n, bool), np.zeros(n, bool)
    sold_lots = np.zeros(n, int)
    equity, exposure, cash_curve, fee_curve, trades, daily = [], [], [], [], [], []
    fees, buys, sells, longest_idle, longest_hold, blocked = 0.0, 0, 0, 0, 0, 0
    hold_days = []
    risk_blocked = 0
    for t in ids:
        signal_date, day = dates[t - 1], dates[t]
        score, close = scores[t - 1], closing[t - 1]
        buy_gate = data["buy_threshold"][t - 1] if "buy_threshold" in data else None
        sell_gate = data["sell_threshold"][t - 1] if "sell_threshold" in data else None
        priority = data["buy_priority"][t - 1] if "buy_priority" in data else score
        sold = set()
        for j, sym in enumerate(symbols):
            if shares[j] <= 1e-9:
                continue
            age = (signal_date - first[j]).days
            longest_hold = max(longest_hold, age)
            longest_idle = max(longest_idle, (signal_date - last_action[j]).days)
            profit = close[j] / (basis[j] / shares[j]) - 1
            peak_price[j] = max(peak_price[j], close[j])
            age_exit = age >= rule.max_hold_days
            score_hit = score[j] >= (sell_gate[j] if sell_gate is not None else rule.sell_score)
            profit_hit = profit >= rule.profit_target
            if rule.exit_mode == "step_trail":
                armed[j] = armed[j] or score_hit or profit_hit
                if sold_lots[j] == 0:
                    trigger = score_hit or profit_hit
                    reason = "先兑现一笔"
                else:
                    step_hit = profit >= rule.profit_target + 0.10 * sold_lots[j]
                    trigger = step_hit or close[j] <= peak_price[j] * (1 - rule.trailing_drop)
                    reason = "下一档盈利兑现" if step_hit else "上涨后回撤"
            elif rule.exit_mode == "trail":
                armed[j] = armed[j] or score_hit or profit_hit
                trigger = armed[j] and close[j] <= peak_price[j] * (1 - rule.trailing_drop)
                reason = "上涨后回撤"
            else:
                trigger = score_hit or profit_hit
                reason = "指数进入贪婪区" if score_hit else "达到止盈门槛"
            if age_exit:
                trigger, reason = True, "持仓到期退出"
            idle_exit = (
                rule.idle_exit_days is not None
                and (signal_date - last_action[j]).days >= rule.idle_exit_days
                and abs(profit) <= rule.idle_exit_band
            )
            if idle_exit and not trigger:
                trigger, reason = True, "横盘无操作退出一笔"
            loss_exit = rule.stop_loss is not None and profit <= -rule.stop_loss
            if loss_exit:
                trigger, reason = True, "达到单只持仓止损门槛"
            if not trigger or (
                not age_exit
                and not loss_exit
                and last_sell_date[j] is not None
                and (signal_date - last_sell_date[j]).days < rule.sell_gap_days
            ):
                continue
            qty, cost, buy_day = lots[j].pop(0)
            gross = qty * opening[t, j]
            fee = gross * rule.fee_rate
            cash += gross - fee
            fees += fee
            shares[j] -= qty
            basis[j] -= cost
            selling[j] = True
            last_sell_date[j] = last_action[j] = day
            sells += 1
            sold_lots[j] += 1
            hold_days.append((day - buy_day).days)
            sold.add(j)
            if not lots[j]:
                shares[j] = basis[j] = 0.0
                selling[j] = armed[j] = False
                first[j] = last_buy_date[j] = last_sell_date[j] = last_action[j] = None
                flat_date[j] = day
                last_buy[j] = np.nan
                peak_price[j] = 0.0
                sold_lots[j] = 0
            if detail:
                trades.append(
                    {
                        "date": str(day.date()),
                        "signal_date": str(signal_date.date()),
                        "symbol": sym,
                        "side": "sell",
                        "reason": reason,
                        "score": float(score[j]),
                        "price": float(opening[t, j]),
                        "quantity": float(qty),
                        "gross_hkd": float(gross * FX),
                        "fee_hkd": float(fee * FX),
                        "realized_pnl_hkd": float((gross - fee - cost) * FX),
                        "position_quantity": float(shares[j]),
                        "position_lots": len(lots[j]),
                        "position_cost_hkd": float(basis[j] * FX),
                        "cash_hkd": float(cash * FX),
                        "portfolio_positions": {
                            s: {
                                "quantity": float(shares[k]),
                                "lots": len(lots[k]),
                                "market_value_hkd": float(shares[k] * opening[t, k] * FX),
                            }
                            for k, s in enumerate(symbols)
                            if shares[k] > 1e-9
                        },
                        "equity_at_open_hkd": float((cash + shares @ opening[t]) * FX),
                    }
                )
        candidates = []
        for j, sym in enumerate(symbols):
            if j in sold or selling[j] or len(lots[j]) >= sizing.max_lots:
                continue
            if shares[j] <= 1e-9:
                if (
                    flat_date[j] is not None
                    and (signal_date - flat_date[j]).days < rule.reentry_days
                ):
                    continue
                eligible = score[j] <= (buy_gate[j] if buy_gate is not None else rule.buy_score)
                reason = "指数进入恐惧区"
            else:
                eligible = (
                    score[j] <= (buy_gate[j] if buy_gate is not None else rule.buy_score)
                    and close[j] <= last_buy[j] * (1 - rule.add_drop)
                    and (signal_date - last_buy_date[j]).days >= rule.buy_gap_days
                )
                reason = "恐惧区内再跌后加仓"
            if eligible:
                candidates.append((priority[j], sym, j, reason))
        if "buy_allowed" in data and not data["buy_allowed"][t - 1]:
            risk_blocked += len(candidates)
            candidates.clear()
        for _, sym, j, reason in sorted(candidates):
            budget = initial * sizing.lot_fraction
            if cash - sizing.reserve_hkd / FX + 1e-9 < budget or (
                shares[j] <= 1e-9 and np.count_nonzero(shares > 1e-9) >= sizing.max_symbols
            ):
                blocked += 1
                continue
            gross = budget / (1 + rule.fee_rate)
            fee = budget - gross
            qty = gross / opening[t, j]
            cash -= budget
            shares[j] += qty
            basis[j] += budget
            lots[j].append((float(qty), float(budget), day))
            last_buy[j] = opening[t, j]
            last_buy_date[j] = last_action[j] = day
            if first[j] is None:
                first[j] = day
                peak_price[j] = opening[t, j]
            fees += fee
            buys += 1
            if detail:
                trades.append(
                    {
                        "date": str(day.date()),
                        "signal_date": str(signal_date.date()),
                        "symbol": sym,
                        "side": "buy",
                        "reason": reason,
                        "score": float(score[j]),
                        "price": float(opening[t, j]),
                        "quantity": float(qty),
                        "gross_hkd": float(gross * FX),
                        "fee_hkd": float(fee * FX),
                        "realized_pnl_hkd": 0.0,
                        "position_quantity": float(shares[j]),
                        "position_lots": len(lots[j]),
                        "position_cost_hkd": float(basis[j] * FX),
                        "cash_hkd": float(cash * FX),
                        "portfolio_positions": {
                            s: {
                                "quantity": float(shares[k]),
                                "lots": len(lots[k]),
                                "market_value_hkd": float(shares[k] * opening[t, k] * FX),
                            }
                            for k, s in enumerate(symbols)
                            if shares[k] > 1e-9
                        },
                        "equity_at_open_hkd": float((cash + shares @ opening[t]) * FX),
                    }
                )
        value = shares * closing[t]
        nav = cash + value.sum()
        equity.append(nav * FX)
        cash_curve.append(cash * FX)
        exposure.append(100 * value.sum() / nav)
        fee_curve.append(fees * FX)
        if detail:
            positions = {
                sym: {
                    "quantity": float(shares[j]),
                    "lots": len(lots[j]),
                    "cost_hkd": float(basis[j] * FX),
                    "market_value_hkd": float(value[j] * FX),
                    "pnl_hkd": float((value[j] - basis[j]) * FX),
                    "profit_pct": float((value[j] / basis[j] - 1) * 100),
                    "first_buy_date": str(first[j].date()),
                    "holding_days": int((day - first[j]).days),
                    "last_buy_price": float(last_buy[j]),
                    "selling": bool(selling[j]),
                    "last_buy_date": str(last_buy_date[j].date()),
                    "last_sell_date": str(last_sell_date[j].date())
                    if last_sell_date[j] is not None
                    else None,
                    "exit_armed": bool(armed[j]),
                    "sold_lots": int(sold_lots[j]),
                    "peak_price": float(max(peak_price[j], closing[t, j])),
                }
                for j, sym in enumerate(symbols)
                if shares[j] > 1e-9
            }
            daily.append(
                {
                    "date": str(day.date()),
                    "equity_hkd": float(nav * FX),
                    "cash_hkd": float(cash * FX),
                    "fees_hkd": float(fees * FX),
                    "positions": positions,
                }
            )
    e = np.asarray(equity)
    peaks = np.maximum.accumulate(np.maximum(e, initial_hkd))
    metrics = {
        "return_pct": float((e[-1] / initial_hkd - 1) * 100),
        "max_drawdown_pct": float(np.min(e / peaks - 1) * 100),
        "ending_equity_hkd": float(e[-1]),
        "mean_exposure_pct": float(np.mean(exposure)),
        "buys": buys,
        "sells": sells,
        "trade_count": buys + sells,
        "fees_hkd": float(fees * FX),
        "blocked_candidates": blocked,
        "max_idle_days": longest_idle,
        "max_hold_days_observed": longest_hold,
        "median_lot_hold_days": float(np.median(hold_days)) if hold_days else None,
    }
    if "buy_allowed" in data:
        metrics["risk_blocked_candidates"] = risk_blocked
    if not detail:
        return metrics
    years, previous = [], initial_hkd
    for year in sorted(set(dates[ids].year)):
        idx = np.flatnonzero(dates[ids].year == year)
        vals = e[idx]
        ys = [t for t in trades if t["date"].startswith(str(year))]
        peaks_y = np.maximum.accumulate(np.maximum(vals, previous))
        years.append(
            {
                "year": int(year),
                "start_equity_hkd": float(previous),
                "end_equity_hkd": float(vals[-1]),
                "return_pct": float((vals[-1] / previous - 1) * 100),
                "max_drawdown_pct": float(np.min(vals / peaks_y - 1) * 100),
                "buys": sum(t["side"] == "buy" for t in ys),
                "sells": sum(t["side"] == "sell" for t in ys),
                "fees_hkd": float(sum(t["fee_hkd"] for t in ys)),
                "realized_pnl_hkd": float(sum(t["realized_pnl_hkd"] for t in ys)),
                "through": str(dates[ids[idx[-1]]].date()),
            }
        )
        previous = vals[-1]
    return {
        "rule": asdict(rule),
        "metrics": metrics,
        "annual": years,
        "trades": trades,
        "daily": daily,
        "start": str(dates[ids[0]].date()),
        "end": str(dates[ids[-1]].date()),
        "symbols": list(symbols),
    }


def output_dir() -> Path:
    return _research_output() / OUT_NAME


def result_bundle() -> dict:
    path = output_dir() / "selected.json"
    if not path.exists():
        raise ValueError("执行方案尚在计算，稍后重新读取")
    result = _read_result(str(path), path.stat().st_mtime_ns)
    tolerance_path = output_dir() / "tolerance_5.json"
    if tolerance_path.exists():
        tolerance = _read_result(str(tolerance_path), tolerance_path.stat().st_mtime_ns)
        result["tolerance_5"] = {
            key: tolerance[key]
            for key in ("rule", "metrics", "annual", "stress2022", "experiment", "end")
        }
    return result


@lru_cache(maxsize=8)
def _read_result(path: str, modified_ns: int) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=12)
def _cached_plan(profile: str, modified_ns: int, cutoff: str) -> dict:
    rule = result_bundle()["profiles"][profile]["rule"]
    return next_open_plan(load_arrays(), ExecutionRule(**rule))


@lru_cache(maxsize=12)
def _live_selected(profile: str, modified_ns: int, cutoff: str) -> dict:
    selected = result_bundle()["profiles"][profile]
    if selected["end"] == cutoff:
        return selected
    # Replay frozen rules on newly appended bars; never re-optimize parameters.
    return simulate(load_arrays(), ExecutionRule(**selected["rule"]),
                    start=selected["start"], detail=True)


def next_open_plan(data: dict, rule: ExecutionRule) -> dict:
    """Replay exact decision gates; next-open prices are unknown and only estimated."""
    import pandas_market_calendars as mcal

    last = data["dates"][-1]
    sessions = mcal.get_calendar("NYSE").valid_days(
        start_date=last + pd.Timedelta(days=1), end_date=last + pd.Timedelta(days=14)
    )
    upcoming = pd.Timestamp(sessions[0].date())
    projected = {
        "dates": data["dates"].append(pd.DatetimeIndex([upcoming])),
        "symbols": data["symbols"],
    }
    for name in ("open", "close", "score"):
        last_value = data["score"][-1] if name == "score" else data["close"][-1]
        projected[name] = np.vstack([data[name], last_value])
    replay = simulate(projected, rule, detail=True)
    actions = [t for t in replay["trades"] if t["date"] == str(upcoming.date())]
    return {
        "signal_date": str(last.date()),
        "next_open_date": str(upcoming.date()),
        "actions": actions,
        "estimate_note": "模拟账户的规则计划；下一开盘成交价未知，数量和资产仅按最新复权收盘估算，不是已成交订单。",
    }


def dashboard(profile: str = "near_best") -> dict:
    _, cutoff, completed = _active_data()
    try:
        selected = _live_selected(profile, (output_dir() / "selected.json").stat().st_mtime_ns, cutoff)
        rule = selected["rule"]
        positions = selected["daily"][-1]["positions"]
        result_cutoff = selected["end"]
        simulation_account = {"cash_hkd": selected["daily"][-1]["cash_hkd"],
                              "position_count": len(positions), "date": result_cutoff}
    except (OSError, ValueError, KeyError):
        rule = asdict(ExecutionRule())
        positions, result_cutoff = {}, None
        simulation_account = None
    items = []
    plan = None
    if result_cutoff == cutoff and (not completed or cutoff >= completed):
        plan = _cached_plan(profile, (output_dir() / "selected.json").stat().st_mtime_ns, cutoff)
    planned = {a["symbol"]: a for a in plan["actions"]} if plan else {}
    for sym in INPUT_SYMBOLS:
        f = input_frame(sym)
        row = f.iloc[-1]
        s = float(row.without_long) if np.isfinite(row.without_long) else None
        pos = positions.get(sym)
        phase = (
            "极度恐惧"
            if s is not None and s <= -60
            else "恐惧"
            if s is not None and s <= -20
            else "中性"
            if s is not None and s < 20
            else "贪婪"
            if s is not None and s < 60
            else "极度贪婪"
            if s is not None
            else "指数不可用"
        )
        if sym not in DEFAULT_SYMBOLS:
            action, reason = "观察品种", "未纳入本轮九只 ETF 组合研究"
        elif result_cutoff != cutoff:
            action, reason = "待重算", "方案与行情日期不同，暂不生成操作"
        elif pos:
            trail_armed = (
                pos.get("exit_armed", False)
                or (s is not None and s >= rule["sell_score"])
                or pos["profit_pct"] >= rule["profit_target"] * 100
            )
            trailing_price = pos.get("peak_price", row.close) * (1 - rule["trailing_drop"])
            if pos["holding_days"] >= rule["max_hold_days"]:
                action, reason = "退出候选", "已达到持仓期限"
            elif rule["exit_mode"] == "step_trail" and (
                (pos.get("sold_lots", 0) == 0 and trail_armed)
                or pos["profit_pct"]
                >= (rule["profit_target"] + 0.10 * pos.get("sold_lots", 0)) * 100
            ):
                action, reason = "卖出一笔候选", "先兑现一笔或达到下一档盈利门槛，仍需核对卖出间隔"
            elif rule["exit_mode"] == "trail" and trail_armed and row.close <= trailing_price:
                action, reason = "卖出一笔候选", "上涨保护已启动且回撤达到门槛，仍需核对卖出间隔"
            elif rule["exit_mode"] == "score_or_profit" and (
                (s is not None and s >= rule["sell_score"])
                or pos["profit_pct"] >= rule["profit_target"] * 100
            ):
                action, reason = "卖出一笔候选", "达到指数或持仓止盈条件，仍需核对交易间隔"
            elif (
                not pos["selling"]
                and pos["lots"] < 4
                and s is not None
                and s <= rule["buy_score"]
                and row.close <= pos["last_buy_price"] * (1 - rule["add_drop"])
            ):
                action, reason = "加仓候选", "指数与跌幅达到条件，仍需核对间隔及现金"
            else:
                action = (
                    "上涨保护持有" if rule["exit_mode"] == "trail" and trail_armed else "模拟持有"
                )
                reason = (
                    f"回撤保护价 ${trailing_price:.2f}（复权）"
                    if rule["exit_mode"] == "trail" and trail_armed
                    else f"本轮已持有 {pos['holding_days']} 天；到期 {rule['max_hold_days']} 天"
                )
        elif s is not None and s <= rule["buy_score"]:
            action, reason = "首笔买入候选", "指数达到恐惧门槛，仍受现金、五只名额和冷却期限制"
        else:
            action, reason = "等待买点", f"指数不高于 {rule['buy_score']} 时考虑首笔"
        if plan and sym in DEFAULT_SYMBOLS:
            if sym in planned:
                order = planned[sym]
                action = "计划买入一笔" if order["side"] == "buy" else "计划卖出一笔"
                reason = f"{order['reason']}；{plan['signal_date']} 收盘信号，{plan['next_open_date']} 下一开盘模拟计划，现金、名额及间隔已核对"
            elif action.endswith("候选"):
                action, reason = (
                    "暂无下一开盘订单",
                    "现金、五只名额、买卖间隔和冷却期全部核对后，当前未产生订单",
                )
        raw = None
        if "raw_close" in f.columns and np.isfinite(row.raw_close):
            raw = float(row.raw_close)
        elif sym in ("TQQQ", "SOXL"):
            from app.services.research_cockpit import benchmark_frame

            b = benchmark_frame(sym)
            if b.index[-1] == f.index[-1]:
                raw = float(b.iloc[-1].close)
        items.append(
            {
                "symbol": sym,
                "date": str(f.index[-1].date()),
                "score": s,
                "adjusted_close": float(row.close),
                "raw_close": raw,
                "phase": phase,
                "action": action,
                "reason": reason,
                "position": pos,
                "previous_score": float(f.iloc[-2].without_long)
                if np.isfinite(f.iloc[-2].without_long)
                else None,
                "price_change_pct": float((row.close / f.iloc[-2].close - 1) * 100),
            }
        )
    return {
        "cutoff": cutoff,
        "last_completed_session": completed,
        "stale": bool(completed and cutoff < completed),
        "index_version": "frozen-two-input-score-minus99-plus99",
        "indicator_scale": indicator_scale(),
        "rule": rule,
        "items": items,
        "initial_hkd": INITIAL_HKD,
        "reserve_hkd": RESERVE * FX,
        "fx_assumption": FX,
        "position_kind": "历史回测期末模拟持仓，不代表个人实际持仓",
        "next_open_plan": plan,
        "simulation_account": simulation_account,
    }


def history_view(symbol: str, limit: int = 600) -> dict:
    frame = input_frame(symbol)
    f = frame if limit == 0 else frame.tail(limit)
    valid = f.without_long.dropna()
    latest = (
        float(frame.iloc[-1].without_long) if np.isfinite(frame.iloc[-1].without_long) else None
    )
    bins = []
    for threshold in (-80, -60, -40, -20, 0, 20, 40, 60, 80):
        count = (
            int((valid <= threshold).sum()) if threshold <= 0 else int((valid >= threshold).sum())
        )
        bins.append(
            {
                "threshold": threshold,
                "operator": "≤" if threshold <= 0 else "≥",
                "count": count,
                "pct": float(count / len(valid) * 100) if len(valid) else None,
            }
        )
    positive = int((valid > 0).sum())
    bins.insert(
        5,
        {
            "threshold": 0,
            "operator": ">",
            "count": positive,
            "pct": float(positive / len(valid) * 100) if len(valid) else None,
        },
    )
    return {
        "symbol": symbol,
        "observations": len(valid),
        "observed_min": float(valid.min()) if len(valid) else None,
        "observed_max": float(valid.max()) if len(valid) else None,
        "distribution": bins,
        "at_or_above_current": int((valid >= latest).sum()) if latest is not None else None,
        "points": [
            {
                "date": str(d.date()),
                "price": float(r.close),
                "score": float(r.without_long) if np.isfinite(r.without_long) else None,
            }
            for d, r in f.iterrows()
        ],
    }
