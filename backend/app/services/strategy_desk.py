"""Small, curated read models; historical archives remain on disk."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from app.services.execution_research import _read_result, output_dir
from app.services.research_cockpit import INPUT_SYMBOLS, _active_data, _research_output
from app.services.sentiment import COMPONENTS, FACTOR_WEIGHTS, build_components, score_index


def curated_strategies() -> dict:
    path = output_dir() / "curated.json"
    value = _read_result(str(path), path.stat().st_mtime_ns)
    _, cutoff, _ = _active_data()
    return {**value, "current_cutoff": cutoff, "stale": value["end"] != cutoff}


def strategy_detail(identifier: str) -> dict:
    cards = curated_strategies()
    selected = next((x for x in cards["items"] if x["id"] == identifier), None)
    if selected is None:
        raise ValueError("未知保留方案")
    path = output_dir() / "curated" / f"{identifier}.json"
    return _read_result(str(path), path.stat().st_mtime_ns)


def observation_summary(symbol: str) -> dict:
    if symbol not in INPUT_SYMBOLS:
        raise ValueError("没有该品种观察数据")
    active, cutoff, completed = _active_data()
    base = _research_output() / "requested_universe_reduction" / "snapshots" / f"{symbol}_snapshot.csv"
    fresh = active / f"{symbol}_public_snapshot.csv" if active else base
    if not base.exists() or not fresh.exists():
        return {"symbol": symbol, "status": "missing", "data_date": None, "latest": None,
                "message": "缺少五项观察的量价数据；交易指数仍单独显示"}
    return _observation_cached(symbol, str(base), base.stat().st_mtime_ns,
                               str(fresh), fresh.stat().st_mtime_ns, cutoff, completed)


@lru_cache(maxsize=32)
def _observation_cached(symbol, base_path, base_modified, fresh_path, fresh_modified, cutoff, completed):
    base = pd.read_csv(base_path, parse_dates=["date"]).set_index("date").sort_index()
    fresh = pd.read_csv(fresh_path, parse_dates=["date"]).set_index("date").sort_index()
    extra = fresh.loc[fresh.index > base.index[-1]].copy()
    if len(extra):
        anchor = base.index[-1]
        if anchor not in fresh.index:
            return {"symbol": symbol, "status": "missing", "data_date": None, "latest": None,
                    "message": "量价观察缺少连续复权锚点，暂停展示"}
        extra["adjusted_close"] *= base.loc[anchor, "adjusted_close"] / fresh.loc[anchor, "adjusted_close"]
    bars = pd.concat([base, extra]).loc[:cutoff]
    if bars.index.has_duplicates:
        raise ValueError("观察数据有重复日期")
    try:
        scored = score_index(build_components(bars))
    except ValueError:
        return {"symbol": symbol, "status": "missing", "data_date": str(bars.index[-1].date()),
                "latest": None, "message": "量价质量不足，暂不展示五项观察"}
    last = scored.iloc[-1]
    date = str(bars.index[-1].date())
    valid = np.isfinite(last["score"])
    return {"symbol": symbol, "data_date": date,
            "status": "stale" if completed and date < completed else "ok" if valid else "insufficient",
            "message": "五项量价观察，与交易用两项输入指数独立，不参与买卖规则",
            "latest": {"score": float(last["score"]), "components": [
                {"key": k, "weight": FACTOR_WEIGHTS[k], "value": float(last[k]),
                 "contribution": float(last[k] * FACTOR_WEIGHTS[k])}
                for k in COMPONENTS]} if valid else None}
