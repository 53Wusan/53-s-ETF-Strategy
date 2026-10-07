"""Independent research refresh; preserves every already-published historical input."""

from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.services.market_data import MarketDataError, YahooChartProvider
from app.services.public_history import PublicHistoryProvider
from app.services.research_cockpit import (
    BENCHMARK_SYMBOLS,
    INPUT_SYMBOLS,
    _active_data,
    _research_output,
    input_frame,
)
from app.services.research_data_refresh import (
    FROZEN_CUTOFF,
    OVERLAP_START,
    _append_fetched,
    _hash,
    _read_csv,
    calculate_inputs,
    last_completed_us_session,
)


def _history_through(symbol, completed):
    """Use a complete daily source; reject stale records before publishing."""
    primary = PublicHistoryProvider().history(symbol, OVERLAP_START, completed)
    primary.index = pd.to_datetime(primary.index)
    if pd.Timestamp(completed) in primary.index:
        return primary
    fallback = YahooChartProvider().history(symbol, OVERLAP_START, completed)
    fallback.index = pd.to_datetime(fallback.index)
    if pd.Timestamp(completed) not in fallback.index:
        raise MarketDataError(f"{symbol} 两个行情源均缺少 {completed} 完整日线")
    fallback.attrs["provider"] = YahooChartProvider.name
    fallback.attrs["source_url"] = f"https://finance.yahoo.com/quote/{symbol}/history/"
    return fallback


def refresh() -> dict:
    completed = last_completed_us_session()
    root = _research_output()
    active, cutoff, _ = _active_data()
    if active and cutoff == completed.isoformat():
        return json.loads((active / "manifest.json").read_text(encoding="utf-8"))
    output_root = root / "forward_data"
    config = json.loads(
        (root.parents[1] / "research/configs/no_yinn_paper_v1.json").read_text(encoding="utf-8")
    )
    symbols = tuple(dict.fromkeys((*INPUT_SYMBOLS, *BENCHMARK_SYMBOLS)))
    fetched = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_history_through, s, completed): s
            for s in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            fetched[symbol] = future.result()
    directory = output_root / f"{completed.isoformat()}-public"
    if directory.exists():
        raise ValueError("该日期的公共源快照已存在；请检查现有清单，不覆盖已发布数据")
    frames, benchmarks, audit = {}, {}, {}
    for symbol in symbols:
        if symbol in INPUT_SYMBOLS:
            base_path = root / "requested_universe_reduction/snapshots" / f"{symbol}_snapshot.csv"
            if (
                symbol in config["snapshot_sha256"]
                and _hash(base_path) != config["snapshot_sha256"][symbol]
            ):
                raise ValueError(f"{symbol} 冻结原始快照哈希改变")
            base = _read_csv(base_path)
            combined, factor = _append_fetched(base, fetched[symbol], symbol, completed)
            calculated = calculate_inputs(combined, config["indicator_parameters"])
            frozen = _read_csv(root / "requested_universe_reduction" / f"{symbol}_inputs.csv")
            for column in frozen.columns:
                np.testing.assert_allclose(
                    calculated.loc[:FROZEN_CUTOFF, column],
                    frozen[column],
                    atol=1e-8,
                    rtol=0,
                    equal_nan=True,
                )
            previous = input_frame(symbol)
            common = calculated.index.intersection(previous.index)
            price_error = max(
                float((calculated.loc[common, c] / previous.loc[common, c] - 1).abs().max())
                for c in ("open", "close")
            )
            score_error = float(
                (calculated.loc[common, "without_long"] - previous.loc[common, "without_long"])
                .abs()
                .max()
            )
            if price_error > 0.002 or score_error > 0.1:
                raise ValueError(
                    f"{symbol} 公共源与已发布快照偏差超限: 价格{price_error:.6g}, 指数{score_error:.6g}"
                )
            # Anchor the new adjusted-price numeraire to the most recent immutable
            # close, not merely the original frozen date. No spurious return at
            # a provider switch; all subsequent returns retain the new source ratio.
            continuity = float(
                previous.iloc[-1].close / combined.loc[previous.index[-1], "adjusted_close"]
            )
            combined.loc[combined.index > previous.index[-1], "adjusted_close"] *= continuity
            committed_extra = common[common > pd.Timestamp(FROZEN_CUTOFF)]
            combined.loc[committed_extra, "adjusted_close"] = previous.loc[committed_extra, "close"]
            calculated = calculate_inputs(combined, config["indicator_parameters"])
            # Do not revise old trades or the formal paper ledger. Preserve all old
            # signal columns exactly, while recording independent source differences.
            for column in (
                "open",
                "close",
                "without_long",
                "without_long_rank",
                "without_long_partial_rank",
            ):
                calculated.loc[common, column] = previous.loc[common, column]
            calculated["raw_close"] = combined.close
            frames[symbol] = calculated
            audit[symbol] = {
                "adjustment_factor": factor,
                "overlap_price_relative_error": price_error,
                "overlap_score_absolute_error": score_error,
                "continuity_factor": continuity,
                "preserved_through": cutoff,
                "new_rows": int((calculated.index > pd.Timestamp(cutoff)).sum()),
                "source_url": fetched[symbol].attrs.get("source_url"),
            }
        if symbol in BENCHMARK_SYMBOLS:
            base = _read_csv(root / "benchmark_qld_tqqq_soxl" / f"{symbol}_snapshot.csv")
            benchmarks[symbol], _ = _append_fetched(base, fetched[symbol], symbol, completed)
            if active:
                old = _read_csv(active / f"{symbol}_benchmark_snapshot.csv")
                continuity = float(
                    old.iloc[-1].adjusted_close
                    / benchmarks[symbol].loc[old.index[-1], "adjusted_close"]
                )
                benchmarks[symbol].loc[
                    benchmarks[symbol].index > old.index[-1], "adjusted_close"
                ] *= continuity
                benchmarks[symbol].loc[old.index, old.columns] = old
    # The frozen reader expects directories named by ISO date. A new date is
    # immutable; stop rather than overwrite an existing published snapshot.
    final_dir = output_root / completed.isoformat()
    if final_dir.exists():
        raise ValueError("最新完整交易日已有快照，不覆盖已发布目录")
    with tempfile.TemporaryDirectory(prefix="stage-public-", dir=output_root) as stage_name:
        from pathlib import Path

        stage = Path(stage_name)
        for symbol, frame in frames.items():
            frame.to_csv(stage / f"{symbol}_inputs.csv", index_label="date")
        for symbol, frame in benchmarks.items():
            frame.to_csv(stage / f"{symbol}_benchmark_snapshot.csv", index_label="date")
        for symbol, frame in fetched.items():
            frame.to_csv(stage / f"{symbol}_public_snapshot.csv", index_label="date")
        manifest = {
            "strategy_version": config["name"],
            "frozen_cutoff": FROZEN_CUTOFF.isoformat(),
            "latest_completed_session": completed.isoformat(),
            "market_last_completed_session": completed.isoformat(),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "retrospective_backfill": True,
            "provider": "+".join(sorted({frame.attrs.get("provider", PublicHistoryProvider.name) for frame in fetched.values()})),
            "source_by_symbol": {symbol: frame.attrs.get("provider", PublicHistoryProvider.name) for symbol, frame in fetched.items()},
            "previous_snapshot": cutoff,
            "symbols": list(symbols),
            "audit": audit,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.rename(stage, final_dir)
    pointer_tmp = output_root / "latest-execution.tmp"
    pointer_tmp.write_text(json.dumps({"date": completed.isoformat()}), encoding="utf-8")
    os.replace(pointer_tmp, output_root / "latest.json")
    return manifest


if __name__ == "__main__":
    try:
        print(json.dumps(refresh(), ensure_ascii=False))
    except (ValueError, MarketDataError) as exc:
        raise SystemExit(str(exc)) from exc
