"""Append-only prospective paper trial, separate from exploratory backtests."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

from app.services.research_cockpit import (
    BENCHMARK_SYMBOLS,
    DEFAULT_SYMBOLS,
    INDEX_VERSION,
    INITIAL,
    VERSION,
    _active_data,
    _research_output,
    compare,
    input_frame,
)
from app.services.research_data_refresh import last_completed_us_session

START = date(2026, 9, 28)
KICKOFF = date(2026, 9, 25)
TARGET_SESSIONS = 20


def _directory() -> Path:
    return _research_output() / "forward_data" / "paper_ledger" / VERSION


def _config_path() -> Path:
    return _research_output().parent / "configs" / f"{VERSION}.json"


def _source_paths() -> dict[str, Path]:
    services = Path(__file__).resolve().parent
    return {
        "trade_calculation": services / "research_cockpit.py",
        "indicator_calculation": services / "research_data_refresh.py",
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _exclusive_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _sessions(through: date) -> list[date]:
    if through < START:
        return []
    return [day.date() for day in mcal.get_calendar("NYSE").valid_days(start_date=START, end_date=through)]


def _next_open(day: date) -> datetime:
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(start_date=day + timedelta(days=1), end_date=day + timedelta(days=10))
    if schedule.empty:
        raise ValueError(f"{day} 之后没有可确认的下一交易日开盘")
    return schedule.market_open.iloc[0].to_pydatetime().astimezone(timezone.utc)


def initialize() -> dict:
    """Freeze the rule, starting cash, benchmark and observable pre-open signals."""
    path = _directory() / "kickoff.json"
    if path.exists():
        return _read(path)
    _, cutoff, _ = _active_data()
    if cutoff != KICKOFF.isoformat():
        raise ValueError(f"前瞻起点必须在 {KICKOFF} 收盘数据冻结；当前数据截至 {cutoff}")
    if last_completed_us_session() >= START:
        raise ValueError("起点交易日已完成，不能事后创建前瞻试验")
    config = _config_path()
    if not config.exists():
        raise ValueError("冻结策略配置缺失")
    signals = {}
    for symbol in DEFAULT_SYMBOLS:
        row = input_frame(symbol).loc[pd.Timestamp(KICKOFF)]
        if not pd.notna(row.without_long_rank):
            raise ValueError(f"{symbol} 起点指标缺失")
        signals[symbol] = {"close": float(row.close), "score": float(row.without_long), "percentile": float(row.without_long_rank)}
    candidates = sorted((symbol for symbol in DEFAULT_SYMBOLS if signals[symbol]["percentile"] <= 20), key=lambda symbol: (signals[symbol]["percentile"], symbol))
    value = {
        "experiment": VERSION,
        "index_version": INDEX_VERSION,
        "status": "precommitted",
        "start_session": START.isoformat(),
        "decision_close": KICKOFF.isoformat(),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "initial_usd_each": INITIAL,
        "pool_symbols": list(DEFAULT_SYMBOLS),
        "benchmark_weights": dict(zip(BENCHMARK_SYMBOLS, (.4, .3, .3), strict=True)),
        "target_sessions": TARGET_SESSIONS,
        "config_sha256": _digest(config),
        "initial_signals": signals,
        "first_open_buy_candidates": candidates,
        "execution": "previous_close_decision_next_adjusted_open",
        "note": "候选不保证成交；成交仍受开盘价、现金和仓位约束。",
    }
    try:
        _exclusive_json(path, value)
    except FileExistsError:
        return _read(path)
    return value


def seal_implementation() -> dict:
    """Commit the exact calculation code before the trial's first close."""
    path = _directory() / "implementation_lock.json"
    if path.exists():
        return _read(path)
    kickoff_path = _directory() / "kickoff.json"
    if not kickoff_path.exists() or last_completed_us_session() >= START:
        raise ValueError("必须在首个交易日完成前冻结计算实现")
    value = {
        "kickoff_sha256": _digest(kickoff_path),
        "source_sha256": {name: _digest(source) for name, source in _source_paths().items()},
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _exclusive_json(path, value)
    except FileExistsError:
        return _read(path)
    return value


def _verified_records() -> tuple[dict | None, list[dict], str | None]:
    directory = _directory()
    kickoff_path = directory / "kickoff.json"
    if not kickoff_path.exists():
        return None, [], None
    kickoff = _read(kickoff_path)
    if kickoff.get("config_sha256") != _digest(_config_path()):
        raise ValueError("冻结策略配置已变化，纸面账本暂停")
    lock_path = directory / "implementation_lock.json"
    if not lock_path.exists():
        raise ValueError("计算实现尚未冻结，纸面账本暂停")
    lock = _read(lock_path)
    if lock.get("kickoff_sha256") != _digest(kickoff_path) or lock.get("source_sha256") != {name: _digest(source) for name, source in _source_paths().items()}:
        raise ValueError("起点或计算实现已变化，纸面账本暂停")
    previous = _digest(lock_path)
    records = []
    for path in sorted(directory.glob("????-??-??.json")):
        record = _read(path)
        if path.stem != record.get("date") or record.get("previous_sha256") != previous:
            raise ValueError(f"纸面账本链条异常：{path.name}")
        records.append(record)
        previous = _digest(path)
    if records and [item["date"] for item in records] != [day.isoformat() for day in _sessions(date.fromisoformat(records[-1]["date"]))]:
        raise ValueError("纸面账本交易日不连续")
    return kickoff, records, previous


def _evaluate(kickoff: dict | None, records: list[dict]) -> dict:
    """Audit the predeclared first 20 sessions; results are provisional before then."""
    window = records[:TARGET_SESSIONS]
    issues = []
    prior_pool_fees = 0.0
    prior_benchmark_fees = 0.0
    allowed = {(symbol, "buy") for symbol in kickoff.get("first_open_buy_candidates", [])} if kickoff else set()
    for record in window:
        payload = record["payload"]
        pool, benchmark = payload["pool"], payload["benchmark"]
        for name, account in (("pool", pool), ("benchmark", benchmark)):
            balance = account["cash"] + sum(position["market_value"] for position in account["positions"].values())
            if abs(balance - account["equity"]) > 1e-6:
                issues.append(f"{record['date']} {name} 现金与持仓不平")
        pool_fees = sum(fill["fee"] for fill in pool["fills"])
        benchmark_fees = sum(fill["fee"] for fill in benchmark["fills"])
        if abs(prior_pool_fees + pool_fees - pool["fees_cumulative"]) > 1e-6:
            issues.append(f"{record['date']} 共享池费用不平")
        if abs(prior_benchmark_fees + benchmark_fees - benchmark["fees_cumulative"]) > 1e-6:
            issues.append(f"{record['date']} 基准费用不平")
        prior_pool_fees = pool["fees_cumulative"]
        prior_benchmark_fees = benchmark["fees_cumulative"]
        for fill in pool["fills"]:
            if (fill["symbol"], fill["side"]) not in allowed:
                issues.append(f"{record['date']} {fill['symbol']} 成交缺少前一收盘信号")
        allowed = {(intent["symbol"], "buy" if intent["side"] == "buy_candidate" else "sell") for intent in pool["next_open_intents"]}
    complete = len(window) == TARGET_SESSIONS
    kickoff_on_time = bool(kickoff and datetime.fromisoformat(kickoff["captured_at_utc"]) < _next_open(KICKOFF))
    late_signals = sum(record.get("signal_precommitted_before_next_open") is False for record in window)
    return {
        "ready_for_four_week_review": complete and not issues,
        "clean_forward_sample": complete and not issues and kickoff_on_time and late_signals == 0,
        "kickoff_before_first_open": kickoff_on_time,
        "late_signals": late_signals,
        "observed_sessions": len(window),
        "required_sessions": TARGET_SESSIONS,
        "audit_issues": issues,
        "delayed_recordings": sum(record.get("recording_delay_days", 0) > 0 for record in window),
        "pool_return_pct": window[-1]["payload"]["pool"]["return_pct"] if window else None,
        "pool_max_drawdown_pct": min((record["payload"]["pool"]["drawdown_pct"] for record in window), default=None),
        "benchmark_return_pct": window[-1]["payload"]["benchmark"]["return_pct"] if window else None,
        "benchmark_max_drawdown_pct": min((record["payload"]["benchmark"]["drawdown_pct"] for record in window), default=None),
    }


def status() -> dict:
    kickoff, records, _ = _verified_records()
    _, cutoff, market_completed = _active_data()
    completed = last_completed_us_session()
    expected = _sessions(min(completed, date.fromisoformat(cutoff)))
    missing = [day.isoformat() for day in expected if day.isoformat() not in {record["date"] for record in records}]
    refresh_path = _research_output() / "forward_data" / "status.json"
    refresh_status = _read(refresh_path) if refresh_path.exists() else {}
    missing_symbols = refresh_status.get("missing_on_requested_session", []) if refresh_status.get("market_last_completed_session") == completed.isoformat() else []
    evaluation = _evaluate(kickoff, records)
    return {
        "kickoff": kickoff,
        "implementation_lock": _read(_directory() / "implementation_lock.json") if kickoff is not None else None,
        "records": records,
        "recorded_sessions": len(records),
        "target_sessions": TARGET_SESSIONS,
        "snapshot_cutoff": cutoff,
        "market_last_completed_session": market_completed,
        "missing_sessions": missing,
        "missing_symbols_on_completed_session": missing_symbols,
        "evaluation": evaluation,
        "state": "not_precommitted" if kickoff is None else "audit_failed" if evaluation["audit_issues"] else "data_lag" if date.fromisoformat(cutoff) < completed and completed >= START else "recording_gap" if missing else "waiting_first_session" if not records else "observation_complete" if len(records) >= TARGET_SESSIONS else "recording",
    }


def record_available() -> dict:
    kickoff, records, previous = _verified_records()
    if kickoff is None:
        raise ValueError("尚未冻结前瞻试验起点")
    _, cutoff, _ = _active_data()
    through = min(date.fromisoformat(cutoff), last_completed_us_session())
    sessions = _sessions(through)
    if not sessions:
        return status()
    if len(records) > len(sessions) or [item["date"] for item in records] != [day.isoformat() for day in sessions[:len(records)]]:
        raise ValueError("纸面账本交易日不连续")
    result = compare(DEFAULT_SYMBOLS, START.isoformat(), through.isoformat(), include_daily=True)
    pool = result["pool"]["daily"]
    benchmark = result["benchmark"]["daily"]
    if [day["date"] for day in pool] != [day.isoformat() for day in sessions]:
        raise ValueError("共同行情缺少交易日，账本暂停")
    active, _, _ = _active_data()
    source_manifest_sha256 = _digest(active / "manifest.json") if active is not None else None
    for index, day in enumerate(sessions):
        payload = {"date": day.isoformat(), "pool": pool[index], "benchmark": benchmark[index]}
        if index < len(records):
            if records[index]["payload"] != payload:
                raise ValueError(f"已记录的 {day} 数据或计算结果发生变化，账本暂停")
            continue
        captured = datetime.now(timezone.utc)
        next_open = _next_open(day)
        record = {
            "date": day.isoformat(),
            "recorded_at_utc": captured.isoformat(),
            "recording_delay_days": max(0, (captured.astimezone(ZoneInfo("America/New_York")).date() - day).days),
            "next_session_open_utc": next_open.isoformat(),
            "signal_precommitted_before_next_open": captured < next_open,
            "source_snapshot_date": through.isoformat(),
            "source_manifest_sha256": source_manifest_sha256,
            "previous_sha256": previous,
            "payload": payload,
        }
        path = _directory() / f"{day}.json"
        try:
            _exclusive_json(path, record)
        except FileExistsError:
            concurrent = _read(path)
            if concurrent.get("previous_sha256") != previous or concurrent.get("payload") != payload:
                raise ValueError(f"并发写入的 {day} 记录不一致，账本暂停") from None
        previous = _digest(path)
    return status()
