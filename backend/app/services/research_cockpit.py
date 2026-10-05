"""Read-only cockpit backed by the frozen September 18 research snapshots."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import BACKEND_DIR

VERSION = "no_yinn_paper_v1"
INDEX_VERSION = "short-position21-rsi14-own252-prior504"
DEFAULT_SYMBOLS = ("TQQQ", "FAS", "GDXU", "CURE", "DFEN", "TECL", "UPRO", "EDC", "UGL")
INPUT_SYMBOLS = ("TQQQ", "SOXL", "FAS", "GDXU", "CONL", "CURE", "LABU", "NAIL", "DFEN", "TECL", "UPRO", "EDC", "UGL", "YINN")
BENCHMARK_SYMBOLS = ("QLD", "TQQQ", "SOXL")
INITIAL = 100_000.0
COST = .001


def _research_output() -> Path:
    for root in (BACKEND_DIR.parent, BACKEND_DIR):
        path = root / "research" / "output"
        if path.exists():
            return path
    raise FileNotFoundError("研究快照未安装")


def _active_data() -> tuple[Path | None, str, str | None]:
    root = _research_output()
    pointer = root / "forward_data" / "latest.json"
    if not pointer.exists():
        return None, "2026-09-18", None
    label = json.loads(pointer.read_text(encoding="utf-8"))["date"]
    date = pd.Timestamp(label).date().isoformat()
    directory = root / "forward_data" / date
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("latest_completed_session") != date:
        raise ValueError("最新研究数据指针与清单不一致")
    from app.services.research_data_refresh import last_completed_us_session

    market_completed = max(last_completed_us_session().isoformat(), manifest.get("market_last_completed_session", date))
    return directory, date, market_completed


@lru_cache(maxsize=96)
def _read_frame(path: str) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"], float_precision="round_trip").set_index("date")


def input_frame(symbol: str) -> pd.DataFrame:
    if symbol not in INPUT_SYMBOLS:
        raise ValueError(f"没有 {symbol} 的冻结指标数据")
    active, cutoff, _ = _active_data()
    path = (active / f"{symbol}_inputs.csv") if active else (_research_output() / "requested_universe_reduction" / f"{symbol}_inputs.csv")
    frame = _read_frame(str(path))
    required = {"open", "close", "without_long", "without_long_rank"}
    if not required.issubset(frame.columns) or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{symbol} 研究快照结构异常")
    return frame.loc[:cutoff]


def benchmark_frame(symbol: str) -> pd.DataFrame:
    if symbol not in BENCHMARK_SYMBOLS:
        raise ValueError(f"没有 {symbol} 的长期持有行情")
    active, cutoff, _ = _active_data()
    path = (active / f"{symbol}_benchmark_snapshot.csv") if active else (_research_output() / "benchmark_qld_tqqq_soxl" / f"{symbol}_snapshot.csv")
    frame = _read_frame(str(path)).loc[:cutoff].copy()
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{symbol} 基准行情结构异常")
    frame["adjusted_open"] = frame.open * frame.adjusted_close / frame.close
    return frame


def catalog() -> dict:
    _, cutoff, market_completed = _active_data()
    status_path = _research_output() / "forward_data" / "status.json"
    refresh_status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    items = []
    for symbol in INPUT_SYMBOLS:
        frame = input_frame(symbol)
        available = frame.dropna(subset=["without_long", "without_long_rank"])
        latest = available.iloc[-1] if len(available) else None
        items.append({
            "symbol": symbol,
            "first_date": str(frame.index[0].date()),
            "latest_date": str(frame.index[-1].date()),
            "score_date": str(available.index[-1].date()) if latest is not None else None,
            "close": float(latest["close"]) if latest is not None else None,
            "score": float(latest["without_long"]) if latest is not None else None,
            "percentile": float(latest["without_long_rank"]) if latest is not None else None,
            "valid_score_days": int(frame["without_long"].notna().sum()),
            "ready": latest is not None,
            "snapshot_age_days": int((pd.Timestamp.now(tz="Asia/Shanghai").date() - frame.index[-1].date()).days),
        })
    return {
        "strategy_version": VERSION,
        "index_version": INDEX_VERSION,
        "snapshot_cutoff": cutoff,
        "market_last_completed_session": market_completed,
        "missing_on_completed_session": refresh_status.get("missing_on_requested_session", [])
        if refresh_status.get("market_last_completed_session") == market_completed else [],
        "default_symbols": DEFAULT_SYMBOLS,
        "available_symbols": INPUT_SYMBOLS,
        "benchmark_symbols": BENCHMARK_SYMBOLS,
        "items": items,
    }


def indicator_history(symbol: str, limit: int = 756) -> dict:
    frame = input_frame(symbol).tail(limit)
    return {
        "symbol": symbol,
        "index_version": INDEX_VERSION,
        "points": [
            {"date": str(date.date()), "price": _number(row.close),
             "score": _number(row.without_long), "percentile": _number(row.without_long_rank)}
            for date, row in frame.iterrows()
        ],
    }


def _number(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _metrics(equity: pd.Series) -> dict:
    drawdown = equity / equity.cummax().clip(lower=INITIAL) - 1
    elapsed_days = (equity.index[-1] - equity.index[0]).days
    return {
        "return_pct": float((equity.iloc[-1] / INITIAL - 1) * 100),
        "drawdown_pct": float(drawdown.min() * 100),
        "cagr_pct": float(((equity.iloc[-1] / INITIAL) ** (365.25 / elapsed_days) - 1) * 100) if elapsed_days >= 365 else None,
        "ending_value": float(equity.iloc[-1]),
        "sessions": len(equity),
    }


def _series_points(equity: pd.Series) -> list[dict]:
    return [{"date": str(date.date()), "equity": float(value)} for date, value in equity.items()]


def _shared_pool(symbols: tuple[str, ...], dates: pd.DatetimeIndex, visible_start: pd.Timestamp, include_daily: bool = False) -> dict:
    frames = {symbol: input_frame(symbol).reindex(dates) for symbol in symbols}
    def matrix(column: str) -> np.ndarray:
        return np.column_stack([frames[symbol][column].to_numpy(float) for symbol in symbols])
    opening, closing, rank = (matrix(name) for name in ("open", "close", "without_long_rank"))
    cash = INITIAL
    shares = np.zeros(len(symbols))
    basis = np.zeros(len(symbols))
    last_buy = np.full(len(symbols), np.nan)
    tech = [j for j, symbol in enumerate(symbols) if symbol in ("TQQQ", "SOXL", "TECL")]
    duplicate = [j for j, symbol in enumerate(symbols) if symbol in ("SPXL", "UPRO")]
    trades = []
    history = []
    daily = []
    total_fees = 0.0
    for t, date in enumerate(dates):
        if t:
            sold = set()
            for j, symbol in enumerate(symbols):
                if shares[j] <= 1e-10:
                    continue
                profit = closing[t - 1, j] / (basis[j] / shares[j]) - 1
                if profit < .55:
                    continue
                quantity = min(shares[j], INITIAL * .10 / opening[t, j])
                gross = quantity * opening[t, j]
                fee = gross * COST
                basis[j] -= quantity * basis[j] / shares[j]
                shares[j] -= quantity
                cash += gross - fee
                total_fees += fee
                sold.add(j)
                trades.append({"date": str(date.date()), "signal_date": str(dates[t - 1].date()), "symbol": symbol, "side": "sell", "reason": "profit55", "price": float(opening[t, j]), "quantity": float(quantity), "fee": float(fee)})
                if shares[j] < 1e-9:
                    shares[j] = basis[j] = 0
                    last_buy[j] = np.nan
            candidates = [j for j in range(len(symbols)) if j not in sold and np.isfinite(rank[t - 1, j]) and rank[t - 1, j] <= 20 and (np.isnan(last_buy[j]) or closing[t - 1, j] <= last_buy[j] * .95)]
            for j in sorted(candidates, key=lambda item: (rank[t - 1, item], symbols[item])):
                room = INITIAL * .25 - basis[j]
                if j in tech:
                    room = min(room, INITIAL * .50 - basis[tech].sum())
                if j in duplicate:
                    room = min(room, INITIAL * .25 - basis[duplicate].sum())
                position = float(np.dot(shares, opening[t]))
                nav = cash + position
                exposure_room = max(0., (.60 * nav - position) * (1 + COST) / (1 + .60 * COST))
                budget = min(INITIAL * .0275, cash, room, exposure_room)
                if budget < INITIAL * .001:
                    continue
                gross = budget / (1 + COST)
                fee = budget - gross
                quantity = gross / opening[t, j]
                cash -= budget
                shares[j] += quantity
                basis[j] += budget
                last_buy[j] = opening[t, j]
                total_fees += fee
                trades.append({"date": str(date.date()), "signal_date": str(dates[t - 1].date()), "symbol": symbols[j], "side": "buy", "reason": "fear5pctgap", "price": float(opening[t, j]), "quantity": float(quantity), "fee": float(fee)})
        value = shares * closing[t]
        if date >= visible_start:
            history.append((cash + value.sum(), cash, *value))
            if include_daily:
                intents = []
                for j, symbol in enumerate(symbols):
                    if shares[j] > 1e-10 and closing[t, j] / (basis[j] / shares[j]) - 1 >= .55:
                        intents.append({"symbol": symbol, "side": "sell", "reason": "profit55"})
                    elif np.isfinite(rank[t, j]) and rank[t, j] <= 20 and (np.isnan(last_buy[j]) or closing[t, j] <= last_buy[j] * .95):
                        intents.append({"symbol": symbol, "side": "buy_candidate", "reason": "fear5pctgap", "percentile": float(rank[t, j])})
                daily.append({"date": str(date.date()), "equity": float(cash + value.sum()), "cash": float(cash), "fees_cumulative": float(total_fees), "positions": {symbol: {"shares": float(shares[j]), "cost_basis": float(basis[j]), "market_value": float(value[j]), "last_buy": _number(last_buy[j])} for j, symbol in enumerate(symbols) if shares[j] > 1e-10}, "signals": {symbol: {"close": _number(closing[t, j]), "score": _number(frames[symbol].iloc[t].without_long), "percentile": _number(rank[t, j])} for j, symbol in enumerate(symbols)}, "next_open_intents": intents, "fills": [trade for trade in trades if trade["date"] == str(date.date())]})
    frame = pd.DataFrame(history, index=dates[dates >= visible_start], columns=["equity", "cash", *symbols])
    metrics = _metrics(frame.equity)
    metrics.update({"fees": float(total_fees), "buys": sum(t["side"] == "buy" for t in trades), "sells": sum(t["side"] == "sell" for t in trades), "mean_exposure_pct": float((1 - frame.cash / frame.equity).mean() * 100)})
    result = {"metrics": metrics, "equity_curve": _series_points(frame.equity), "trades": trades}
    if include_daily:
        peak = INITIAL
        for item in daily:
            peak = max(peak, item["equity"])
            item["return_pct"] = (item["equity"] / INITIAL - 1) * 100
            item["drawdown_pct"] = (item["equity"] / peak - 1) * 100
        result["daily"] = daily
    return result


def _hold(symbols: tuple[str, ...], weights: tuple[float, ...], dates: pd.DatetimeIndex, include_daily: bool = False) -> dict:
    frames = {symbol: benchmark_frame(symbol).reindex(dates) for symbol in symbols}
    opens = np.array([frames[symbol].iloc[0].adjusted_open for symbol in symbols])
    prices = np.column_stack([frames[symbol].adjusted_close.to_numpy(float) for symbol in symbols])
    shares = INITIAL * np.array(weights) / (1 + COST) / opens
    equity = pd.Series(prices @ shares, index=dates)
    result = {"metrics": _metrics(equity), "equity_curve": _series_points(equity), "trades": []}
    if include_daily:
        first_fills = [{"date": str(dates[0].date()), "symbol": symbol, "side": "buy", "reason": "benchmark_initial_allocation", "price": float(opens[j]), "quantity": float(shares[j]), "fee": float(INITIAL * weights[j] * COST / (1 + COST))} for j, symbol in enumerate(symbols)]
        peak = INITIAL
        daily = []
        for t, date in enumerate(dates):
            nav = float(equity.iloc[t])
            peak = max(peak, nav)
            daily.append({"date": str(date.date()), "equity": nav, "cash": 0.0, "fees_cumulative": float(INITIAL * COST / (1 + COST)), "positions": {symbol: {"shares": float(shares[j]), "market_value": float(shares[j] * prices[t, j])} for j, symbol in enumerate(symbols)}, "fills": first_fills if t == 0 else [], "return_pct": (nav / INITIAL - 1) * 100, "drawdown_pct": (nav / peak - 1) * 100})
        result["daily"] = daily
    return result


def compare(symbols: tuple[str, ...], start: str, end: str, include_daily: bool = False) -> dict:
    _, cutoff, _ = _active_data()
    if not symbols or len(symbols) > len(INPUT_SYMBOLS) or len(set(symbols)) != len(symbols) or any(symbol not in INPUT_SYMBOLS for symbol in symbols):
        raise ValueError(f"请选择1至{len(INPUT_SYMBOLS)}只不同的已有指标ETF")
    begin, finish = pd.Timestamp(start), pd.Timestamp(end)
    if finish < begin or (finish - begin).days > 365 * 15:
        raise ValueError("日期范围不正确或超过15年")
    all_symbols = tuple(dict.fromkeys((*symbols, *BENCHMARK_SYMBOLS)))
    frames = {symbol: input_frame(symbol) if symbol in symbols else benchmark_frame(symbol) for symbol in all_symbols}
    common = pd.DatetimeIndex(sorted(set.intersection(*(set(frame.index) for frame in frames.values()))))
    dates = common[(common >= begin) & (common <= finish) & (common <= pd.Timestamp(cutoff))]
    if len(dates) < (1 if include_daily else 2):
        raise ValueError("选定区间内没有足够的共同交易日")
    for symbol in symbols:
        if not input_frame(symbol).reindex(dates)[["open", "close"]].gt(0).all().all():
            raise ValueError(f"{symbol} 缺少有效交易价格")
    earlier = common[common < dates[0]]
    simulation_dates = dates.insert(0, earlier[-1]) if len(earlier) else dates
    pool = _shared_pool(symbols, simulation_dates, dates[0], include_daily)
    benchmark = _hold(BENCHMARK_SYMBOLS, (.4, .3, .3), dates, include_daily)
    return {
        "strategy_version": VERSION,
        "index_version": INDEX_VERSION,
        "snapshot_cutoff": cutoff,
        "requested_start": start,
        "requested_end": end,
        "actual_start": str(dates[0].date()),
        "actual_end": str(dates[-1].date()),
        "symbols": symbols,
        "benchmark_symbols": BENCHMARK_SYMBOLS,
        "warnings": (["共同可交易区间从所选起点之后开始"] if dates[0] > begin else [])
        + (["结束日期被现有行情截短"] if dates[-1] < finish else []),
        "pool": pool,
        "benchmark": benchmark,
    }
