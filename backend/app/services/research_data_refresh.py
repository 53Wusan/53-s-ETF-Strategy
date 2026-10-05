"""Append completed US sessions to the frozen research inputs without rewriting them."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from scipy.signal import lfilter

from app.models import QualityStatus
from app.services.market_data import YahooChartProvider, validate_frame
from app.services.research_cockpit import BENCHMARK_SYMBOLS, INPUT_SYMBOLS, _research_output
from app.services.sentiment import rolling_rank, rsi, stochastic

FROZEN_CUTOFF = date(2026, 9, 18)
OVERLAP_START = date(2026, 9, 11)


def last_completed_us_session(now: datetime | None = None) -> date:
    moment = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    candidate = moment.date() if (moment.hour, moment.minute) >= (16, 30) else moment.date() - timedelta(days=1)
    return _completed_session_for_candidate(candidate)


@lru_cache(maxsize=32)
def _completed_session_for_candidate(candidate: date) -> date:
    sessions = mcal.get_calendar("NYSE").valid_days(start_date=candidate - timedelta(days=14), end_date=candidate)
    return sessions[-1].date()


def _rank(score: pd.Series, minimum: int = 504) -> pd.Series:
    def rank(window: np.ndarray) -> float:
        if not np.isfinite(window[-1]):
            return np.nan
        previous = window[:-1]
        previous = previous[np.isfinite(previous)]
        return float(100 * np.mean(previous <= window[-1])) if len(previous) >= minimum else np.nan

    return score.rolling(505, min_periods=minimum + 1).apply(rank, raw=True)


def calculate_inputs(bars: pd.DataFrame, parameters: list[float]) -> pd.DataFrame:
    """Reproduce the frozen two-input model with its exact causal warmup."""
    p = np.asarray(parameters, dtype=float)
    if len(p) != 5 or p[2] != 0 or not 0 <= p[4] < 1:
        raise ValueError("冻结指标参数不符合两项输入模型")
    features = pd.DataFrame({
        "stoch_21": stochastic(bars, 21),
        "stoch_252": stochastic(bars, 252),
        "rsi_rank252": rolling_rank(rsi(bars.adjusted_close.astype(float), 14), 252, 126),
    }).clip(-100, 100)
    valid = features.dropna()
    drive = p[0] + valid.to_numpy() @ p[1:4] / 100
    latent = lfilter([1 - p[4]], [1, -p[4]], drive)
    score = pd.Series(np.nan, index=bars.index)
    score.loc[valid.index] = np.clip(100 * np.tanh(latent), -99, 99)
    close = bars.adjusted_close.astype(float)
    return pd.DataFrame({
        "close": close,
        "open": bars.open.astype(float) * close / bars.close.astype(float),
        "without_long": score,
        "without_long_rank": _rank(score),
        "without_long_partial_rank": _rank(score, 126),
    })


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"], float_precision="round_trip").set_index("date")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_status(output_root: Path, status: dict) -> None:
    temporary = output_root / "status.tmp"
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, output_root / "status.json")


def _append_fetched(base: pd.DataFrame, fetched: pd.DataFrame, symbol: str, through: date) -> tuple[pd.DataFrame, float]:
    baseline_end = pd.Timestamp(FROZEN_CUTOFF)
    overlap = base[["close", "adjusted_close"]].join(
        fetched[["close", "adjusted_close"]], how="inner", lsuffix="_frozen", rsuffix="_fresh"
    ).loc[OVERLAP_START:FROZEN_CUTOFF]
    if len(overlap) < 5:
        raise ValueError(f"{symbol} 与冻结行情重叠不足5天")
    raw_error = (overlap.close_fresh / overlap.close_frozen - 1).abs().max()
    ratio = overlap.adjusted_close_fresh / overlap.adjusted_close_frozen
    factor = float(ratio.median())
    if raw_error > .002 or not .95 <= factor <= 1.05 or (ratio / factor - 1).abs().max() > .0001:
        raise ValueError(f"{symbol} 重叠行情不是稳定复权比例，暂停更新")
    extra = fetched.loc[fetched.index > baseline_end]
    expected = {pd.Timestamp(session.date()) for session in mcal.get_calendar("NYSE").valid_days(start_date=FROZEN_CUTOFF + timedelta(days=1), end_date=through)}
    if set(extra.index) != expected:
        missing = sorted(expected - set(extra.index))
        raise ValueError(f"{symbol} 缺少完整交易日: {missing}")
    if extra.empty or extra.volume.le(0).any():
        raise ValueError(f"{symbol} 新行情为空或成交量无效")
    quality = validate_frame(extra)
    if quality.status != QualityStatus.OK:
        raise ValueError(f"{symbol} 新行情质量未通过: {quality.messages}")
    # Preserve the frozen historical numeraire. Yahoo restates past adjusted
    # closes after distributions; divide new bars by that constant factor.
    normalized_extra = extra.copy()
    normalized_extra["adjusted_close"] /= factor
    bridge = validate_frame(pd.concat([base.tail(1), normalized_extra]))
    if bridge.status != QualityStatus.OK:
        raise ValueError(f"{symbol} 冻结日到新交易日的价格连接异常: {bridge.messages}")
    return pd.concat([base, normalized_extra]).sort_index(), factor


def refresh(through: date | None = None) -> dict:
    completed = last_completed_us_session()
    requested = through or completed
    if requested > completed or requested <= FROZEN_CUTOFF:
        raise ValueError(f"只可更新至已收盘且晚于冻结日的交易日，当前最晚 {completed}")
    root = _research_output()
    output_root = root / "forward_data"
    config_path = root.parents[1] / "research" / "configs" / "no_yinn_paper_v1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    symbols = tuple(dict.fromkeys((*INPUT_SYMBOLS, *BENCHMARK_SYMBOLS)))
    fetched = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(YahooChartProvider().history, symbol, OVERLAP_START, requested): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            fetched[symbol] = future.result()
            fetched[symbol].index = pd.to_datetime(fetched[symbol].index)
    if through is None:
        sessions = [pd.Timestamp(session.date()) for session in mcal.get_calendar("NYSE").valid_days(start_date=FROZEN_CUTOFF + timedelta(days=1), end_date=requested)]
        target = FROZEN_CUTOFF
        for session in sessions:
            if all(session in frame.index for frame in fetched.values()):
                target = session.date()
            else:
                break
        if target == FROZEN_CUTOFF:
            raise ValueError("所有ETF尚无共同的新完整交易日")
    else:
        target = through
    final_dir = output_root / target.isoformat()
    output_root.mkdir(parents=True, exist_ok=True)
    missing = sorted(symbol for symbol, frame in fetched.items() if pd.Timestamp(requested) not in frame.index)
    status = {
        "market_last_completed_session": completed.isoformat(),
        "data_through": target.isoformat(),
        "missing_on_requested_session": missing,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if final_dir.exists():
        _write_status(output_root, status)
        return json.loads((final_dir / "manifest.json").read_text(encoding="utf-8"))
    prepared_inputs = {}
    prepared_benchmarks = {}
    audit = {}
    for symbol in symbols:
        if symbol in INPUT_SYMBOLS:
            base_path = root / "requested_universe_reduction" / "snapshots" / f"{symbol}_snapshot.csv"
            frozen = _read_csv(base_path)
            if symbol in config["snapshot_sha256"] and _hash(base_path) != config["snapshot_sha256"][symbol]:
                raise ValueError(f"{symbol} 冻结快照哈希不一致")
            combined, adjustment = _append_fetched(frozen, fetched[symbol], symbol, target)
            calculated = calculate_inputs(combined, config["indicator_parameters"])
            old = _read_csv(root / "requested_universe_reduction" / f"{symbol}_inputs.csv")
            prefix = calculated.loc[:FROZEN_CUTOFF]
            if not prefix.index.equals(old.index):
                raise ValueError(f"{symbol} 历史日期与冻结指标不一致")
            max_deviation = 0.0
            for column in ("close", "open", "without_long", "without_long_rank", "without_long_partial_rank"):
                deviation = (prefix[column] - old[column]).abs().max(skipna=True)
                if not np.isfinite(deviation) or deviation > 1e-8 or not prefix[column].isna().equals(old[column].isna()):
                    raise ValueError(f"{symbol} 历史{column}与冻结计算不一致: {deviation}")
                max_deviation = max(max_deviation, float(deviation))
            prepared_inputs[symbol] = calculated
            audit[symbol] = {"adjustment_factor": adjustment, "new_rows": len(combined) - len(frozen), "frozen_prefix_max_error": max_deviation}
        if symbol in BENCHMARK_SYMBOLS:
            base = _read_csv(root / "benchmark_qld_tqqq_soxl" / f"{symbol}_snapshot.csv")
            prepared_benchmarks[symbol], _ = _append_fetched(base, fetched[symbol], symbol, target)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=output_root) as staging_name:
        staging = Path(staging_name)
        for symbol, frame in prepared_inputs.items():
            frame.to_csv(staging / f"{symbol}_inputs.csv", index_label="date")
        for symbol, frame in prepared_benchmarks.items():
            frame.to_csv(staging / f"{symbol}_benchmark_snapshot.csv", index_label="date")
        manifest = {
            "strategy_version": config["name"],
            "frozen_cutoff": FROZEN_CUTOFF.isoformat(),
            "latest_completed_session": target.isoformat(),
            "market_last_completed_session": completed.isoformat(),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "retrospective_backfill": target < datetime.now(ZoneInfo("America/New_York")).date(),
            "symbols": list(symbols),
            "audit": audit,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.rename(staging, final_dir)
    latest_tmp = output_root / "latest.tmp"
    latest_tmp.write_text(json.dumps({"date": target.isoformat()}), encoding="utf-8")
    os.replace(latest_tmp, output_root / "latest.json")
    _write_status(output_root, status)
    return manifest
