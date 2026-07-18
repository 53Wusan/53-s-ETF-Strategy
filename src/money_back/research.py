from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import simulate_portfolio
from .data import (
    CORE_GATE_INDICES,
    ETF_SYMBOLS,
    INDEX_SYMBOLS,
    detect_adjustment_jumps,
    field_matrix,
    load_market_data,
    validate_price_frame,
)
from .metrics import annual_returns, performance_metrics, rolling_wealth_multiples
from .models import (
    AcceptanceCriteria,
    ExecutionSpec,
    RunManifest,
    UniverseRules,
    json_safe,
    write_immutable_json,
)
from .signal import generate_daily_signal
from .strategies import build_targets, preregistered_specs
from .universe import evaluate_data_gate
from .validation import choose_candidate, evaluate_acceptance, neighbor_stability


def _git_revision() -> str:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.call(
            ["git", "diff", "--quiet"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_config(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_security_master(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": str})
    for column in ["cross_border", "leveraged_inverse"]:
        frame[column] = frame[column].astype(str).str.lower().map({"true": True, "false": False})
    return frame


def _fixed_exploratory_eligibility(
    adjusted_close: pd.DataFrame,
    master: pd.DataFrame,
    minimum_listing_days: int,
) -> pd.DataFrame:
    price_age = adjusted_close.notna().cumsum()
    eligibility = adjusted_close.notna() & price_age.ge(minimum_listing_days)
    records = master.set_index(master["symbol"].astype(str))
    for symbol in eligibility.columns:
        if symbol not in records.index:
            eligibility[symbol] = False
            continue
        row = records.loc[symbol]
        in_scope = (
            row["asset_type"] == "equity_etf"
            and not bool(row["cross_border"])
            and not bool(row["leveraged_inverse"])
        )
        eligibility[symbol] &= in_scope
    return eligibility


def _matrix_set(bundle) -> dict[str, pd.DataFrame]:
    calendar = bundle.adjusted["上证指数"].index
    etfs = list(ETF_SYMBOLS)
    return {
        "calendar": calendar,
        "adjusted_close": field_matrix(bundle.adjusted, etfs, "close", calendar),
        "index_close": field_matrix(bundle.adjusted, CORE_GATE_INDICES, "close", calendar),
        "raw_open": field_matrix(bundle.raw, etfs, "open", calendar),
        "raw_close": field_matrix(bundle.raw, etfs, "close", calendar),
        "raw_high": field_matrix(bundle.raw, etfs, "high", calendar),
        "raw_low": field_matrix(bundle.raw, etfs, "low", calendar),
        "raw_volume": field_matrix(bundle.raw, etfs, "volume", calendar),
        "adjusted_open": field_matrix(bundle.adjusted, etfs, "open", calendar),
        "adjusted_high": field_matrix(bundle.adjusted, etfs, "high", calendar),
        "adjusted_low": field_matrix(bundle.adjusted, etfs, "low", calendar),
        "adjusted_volume": field_matrix(bundle.adjusted, etfs, "volume", calendar),
    }


def _run_one(
    *,
    spec,
    matrices: dict[str, pd.DataFrame],
    eligibility: pd.DataFrame,
    execution: ExecutionSpec,
    start: str,
    end: str,
    median_turnover_amount_20d: pd.DataFrame | None = None,
    account_value: float = 2_000_000.0,
) -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame, pd.Series]:
    targets, scores, gate = build_targets(
        matrices["adjusted_close"], matrices["index_close"], eligibility, spec
    )
    backtest = simulate_portfolio(
        targets,
        matrices["raw_open"],
        matrices["raw_close"],
        matrices["raw_high"],
        matrices["raw_low"],
        matrices["raw_volume"],
        start=start,
        end=end,
        execution=execution,
        account_value=account_value,
        median_turnover_amount_20d=median_turnover_amount_20d,
        adjusted_open=matrices["adjusted_open"],
        adjusted_close=matrices["adjusted_close"],
        adjusted_high=matrices["adjusted_high"],
        adjusted_low=matrices["adjusted_low"],
    )
    return backtest, performance_metrics(backtest), targets, scores, gate


def run_v0_1_regression(matrices: dict[str, pd.DataFrame]) -> dict:
    from .strategies import t5_spec

    spec = t5_spec("t5_v0_1_regression")
    eligibility = matrices["adjusted_close"].notna()
    targets, _, _ = build_targets(
        matrices["adjusted_close"], matrices["index_close"], eligibility, spec
    )
    execution = ExecutionSpec(execution="next_open", one_way_transaction_cost=0.001)
    backtest = simulate_portfolio(
        targets,
        matrices["adjusted_open"],
        matrices["adjusted_close"],
        matrices["adjusted_high"],
        matrices["adjusted_low"],
        matrices["adjusted_volume"],
        start="2023-09-01",
        end="2026-07-08",
        execution=execution,
    )
    return performance_metrics(backtest)


def _benchmark_from_close(close: pd.Series, start: str, end: str) -> dict:
    series = close.loc[pd.Timestamp(start) : pd.Timestamp(end)].dropna()
    returns = series.pct_change(fill_method=None).fillna(0.0)
    returns.iloc[0] -= 0.001
    equity = (1.0 + returns).cumprod()
    frame = pd.DataFrame(
        {
            "equity": equity,
            "net_return": returns,
            "turnover": 0.0,
            "exposure": 1.0,
            "unfilled_weight": 0.0,
            "participation_violation": False,
            "w_benchmark": 1.0,
        }
    )
    frame.iloc[0, frame.columns.get_loc("turnover")] = 1.0
    frame["drawdown"] = frame["equity"] / frame["equity"].cummax() - 1.0
    return performance_metrics(frame)


def _safe_number(value) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.3f}"


def _write_markdown_report(
    output_path: Path,
    *,
    generated_at: str,
    data_gate: dict,
    regression: dict,
    summary: pd.DataFrame,
    decisions: list[dict],
    overall: dict,
    analysis_start: str,
) -> None:
    baseline = summary[(summary["strategy_id"] == "t5_v0_2_baseline") & (summary["scenario"] == "base")].iloc[0]
    lines = [
        "# Money Back V0.2 严格验证报告",
        "",
        f"> 生成时间：{generated_at}",
        "",
        "## 技术结论",
        "",
        f"- **最终决策：{overall['decision']}。** {overall['reason']}",
        f"- **数据闸门：{data_gate['status']}。** 当前免费数据没有证明退市 ETF 全覆盖、成交额口径和独立第二价格源，因此结果只能称为固定池探索。",
        f"- V0.1 回归锚点仍为净值 `{regression['ending_equity']:.6f}`、最大回撤 `{regression['max_drawdown']:.2%}`。",
        f"- V0.2 固定池基准的滚动三年中位倍数为 `{_safe_number(baseline['median_multiple'])}`，最大回撤为 `{baseline['max_drawdown']:.2%}`；它不能越过数据闸门。",
        "",
        "## 预注册策略结果",
        "",
        f"固定池性能区间从 `{analysis_start}` 开始，即当前资产边界首次出现两只满足 120 个交易日历史的 ETF。结果使用复权收盘计算信号、原始 OHLC4 作为次日 TWAP 代理、单边 10bp；压力情景使用延迟至第二个开盘并收取 20bp。",
        "",
        "| 策略 | 情景 | 期末净值 | CAGR | 最大回撤 | 滚动3年中位倍数 | 年操作日 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"| {row['strategy_id']} | {row['scenario']} | {_safe_number(row['ending_equity'])} | {row['cagr']:.1%} | {row['max_drawdown']:.1%} | {_safe_number(row['median_multiple'])} | {row['trade_days_per_year']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## 数据与口径",
            "",
            "- 研究区间目标为 2013-01-01 至数据截止日；现有六只截图 ETF 最早只有通信 ETF 可追溯至 2019 年，其余多在 2021 年后上市。",
            "- 513120 为跨境港股 ETF，不属于本轮严格的境内股票 ETF 资产边界，只保留在 V0.1 重建回归中。",
            "- 当前价格来自同一免费供应端的复权与原始序列，不能充当真正的双源核对。",
            "- 免费名册没有证明包含历史退市 ETF，存在幸存者偏差；因此性能结果不用于实盘授权。",
            "",
            "## 验证与限制",
            "",
            "- 所有预注册策略均在同一执行与成本引擎下比较，没有进行组合式参数暴力搜索。",
            "- 2023-09 至 2026-07 是已见重建样本；当前没有真正的前向样本外证据。",
            "- 只有数据闸门与性能门槛同时通过，系统才会解锁 12 周纸面跟踪；本次未解锁网页和实盘信号。",
            "",
            "## 下一步",
            "",
            "1. 补齐含退市状态的历史 ETF 主数据，以及独立第二行情源和可信成交额。",
            "2. 在不修改预注册规格的前提下重新运行严格研究。",
            "3. 如果仍无策略通过，保留否定性结论并停止继续调参。",
            "",
            "## 进一步问题",
            "",
            "- 免费数据能否完整恢复 2013 年以来已退市 ETF，是继续严格验证的唯一关键问题。",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_strict_research(
    config_path: str | Path = "configs/t5_v0_2.json",
    *,
    refresh: bool = False,
) -> dict:
    config = load_config(config_path)
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    master = load_security_master(config["security_master"])
    bundle = load_market_data(
        config["research_start"],
        config["research_end"],
        cache_dir=config.get("cache_dir", "data/cache"),
        refresh=refresh,
        include_raw=True,
    )
    matrices = _matrix_set(bundle)

    issues = []
    for label in ETF_SYMBOLS:
        issues.extend(validate_price_frame(label, bundle.adjusted[label]))
        issues.extend(
            validate_price_frame(
                label, bundle.raw[label], reference_calendar=matrices["calendar"]
            )
        )
        issues.extend(
            detect_adjustment_jumps(
                bundle.raw[label]["close"], bundle.adjusted[label]["close"], label
            )
        )
    gate = evaluate_data_gate(
        master=master,
        includes_delisted=False,
        turnover_amount=None,
        dual_source_symbols=set(),
        expected_symbols=set(ETF_SYMBOLS),
        required_start="2016-01-01",
        additional_issues=issues,
    )
    eligibility = _fixed_exploratory_eligibility(
        matrices["adjusted_close"], master, config["universe_rules"]["minimum_listing_days"]
    )
    eligible_counts = eligibility.sum(axis=1)
    active_dates = eligible_counts.index[eligible_counts >= 2]
    if active_dates.empty:
        raise RuntimeError("Fixed-pool fallback never has two eligible in-scope ETFs")
    analysis_start = max(
        pd.Timestamp(config["research_start"]), pd.Timestamp(active_dates[0])
    ).date().isoformat()
    base_execution = ExecutionSpec(
        execution="next_twap_proxy", one_way_transaction_cost=0.001
    )
    stress_execution = ExecutionSpec(
        execution="next_open_delayed", one_way_transaction_cost=0.002
    )
    criteria = AcceptanceCriteria()

    specs = preregistered_specs()
    run_records: list[dict] = []
    backtests: dict[tuple[str, str], pd.DataFrame] = {}
    signal_material = None
    for spec in specs:
        base, base_metrics, targets, scores, strategy_gate = _run_one(
            spec=spec,
            matrices=matrices,
            eligibility=eligibility,
            execution=base_execution,
            start=analysis_start,
            end=config["research_end"],
            account_value=config["universe_rules"]["account_value"],
        )
        stress, stress_metrics, _, _, _ = _run_one(
            spec=spec,
            matrices=matrices,
            eligibility=eligibility,
            execution=stress_execution,
            start=analysis_start,
            end=config["research_end"],
            account_value=config["universe_rules"]["account_value"],
        )
        backtests[(spec.strategy_id, "base")] = base
        backtests[(spec.strategy_id, "stress")] = stress
        run_records.append(
            {
                "strategy_id": spec.strategy_id,
                "spec": spec,
                "base_metrics": base_metrics,
                "stress_metrics": stress_metrics,
            }
        )
        if spec.strategy_id == "t5_v0_2_baseline":
            signal_material = (spec, targets, scores, strategy_gate)

    baseline_record = next(row for row in run_records if row["strategy_id"] == "t5_v0_2_baseline")
    neighbor_rows = [
        {"strategy_id": row["strategy_id"], **row["base_metrics"]}
        for row in run_records
        if row["strategy_id"].startswith("t5_neighbor_")
    ]
    stability = neighbor_stability(
        baseline_record["base_metrics"]["median_multiple"], neighbor_rows, criteria
    )
    decisions = []
    for row in run_records:
        acceptance = evaluate_acceptance(
            strategy_id=row["strategy_id"],
            base_metrics=row["base_metrics"],
            stress_metrics=row["stress_metrics"],
            data_gate=gate,
            criteria=criteria,
            stability=stability if row["strategy_id"] == "t5_v0_2_baseline" else None,
        )
        decisions.append(
            {
                **acceptance,
                "base_metrics": row["base_metrics"],
                "stress_metrics": row["stress_metrics"],
            }
        )
    overall = choose_candidate(decisions)
    regression = run_v0_1_regression(matrices)

    summary_rows = []
    for row in run_records:
        summary_rows.append({"strategy_id": row["strategy_id"], "scenario": "base", **row["base_metrics"]})
        summary_rows.append({"strategy_id": row["strategy_id"], "scenario": "stress", **row["stress_metrics"]})
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output_dir / "strategy_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(list(gate.issues)).to_csv(
        output_dir / "data_quality_issues.csv", index=False, encoding="utf-8-sig"
    )
    bundle.source_manifest.to_csv(
        output_dir / "source_manifest.csv", index=False, encoding="utf-8-sig"
    )

    rolling_rows = []
    annual_rows = []
    for (strategy_id, scenario), backtest in backtests.items():
        for date, value in rolling_wealth_multiples(backtest).items():
            rolling_rows.append(
                {"date": date.date().isoformat(), "strategy_id": strategy_id, "scenario": scenario, "multiple": value}
            )
        for date, value in annual_returns(backtest).items():
            annual_rows.append(
                {"year": date.year, "strategy_id": strategy_id, "scenario": scenario, "return": value}
            )
    pd.DataFrame(rolling_rows).to_csv(
        output_dir / "rolling_3y_multiples.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(annual_rows).to_csv(
        output_dir / "annual_returns.csv", index=False, encoding="utf-8-sig"
    )

    index_benchmarks = []
    for label in ["沪深300", "中证500", "创业板指"]:
        metrics = _benchmark_from_close(
            bundle.adjusted[label]["close"], analysis_start, config["research_end"]
        )
        index_benchmarks.append({"benchmark": label, **metrics})
    equal_weight_targets = eligibility.div(eligibility.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    equal_weight_backtest = simulate_portfolio(
        equal_weight_targets,
        matrices["raw_open"],
        matrices["raw_close"],
        matrices["raw_high"],
        matrices["raw_low"],
        matrices["raw_volume"],
        start=analysis_start,
        end=config["research_end"],
        execution=base_execution,
        adjusted_open=matrices["adjusted_open"],
        adjusted_close=matrices["adjusted_close"],
        adjusted_high=matrices["adjusted_high"],
        adjusted_low=matrices["adjusted_low"],
    )
    index_benchmarks.append(
        {"benchmark": "合格固定池等权", **performance_metrics(equal_weight_backtest)}
    )
    pd.DataFrame(index_benchmarks).to_csv(
        output_dir / "benchmark_summary.csv", index=False, encoding="utf-8-sig"
    )

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    decision_payload = {
        **overall,
        "generated_at": generated_at,
        "data_gate": gate.to_dict(),
        "v0_1_regression": regression,
        "acceptance_results": decisions,
    }
    (output_dir / "decision.json").write_text(
        json.dumps(json_safe(decision_payload), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _write_markdown_report(
        output_dir / "strict_validation_report.md",
        generated_at=generated_at,
        data_gate=gate.to_dict(),
        regression=regression,
        summary=summary,
        decisions=decisions,
        overall=overall,
        analysis_start=analysis_start,
    )

    if signal_material is not None:
        spec, targets, scores, strategy_gate = signal_material
        latest = targets.index[-1]
        current = targets.shift(1).loc[latest].fillna(0.0).to_dict()
        signal = generate_daily_signal(
            spec=spec,
            targets=targets,
            scores=scores,
            gate=strategy_gate,
            current_weights=current,
            universe=eligibility.columns[eligibility.loc[latest]].astype(str).tolist(),
            provenance={
                "config": str(config_path),
                "data_gate": gate.status,
                "source_manifest": str(output_dir / "source_manifest.csv"),
            },
            warnings=[
                "RESEARCH ONLY: the point-in-time data gate failed.",
                "This preview is not an authorization to trade.",
            ],
        )
        write_immutable_json(
            output_dir
            / "signals"
            / f"research_preview_signal_{signal.data_as_of}_{datetime.now().strftime('%H%M%S')}.json",
            signal,
        )

    manifest = RunManifest.create(
        run_id=f"v0_2_{datetime.now().strftime('%Y%m%dT%H%M%S')}",
        strategy=baseline_record["spec"],
        execution=base_execution,
        universe=UniverseRules(**config["universe_rules"]),
        data_start=analysis_start,
        data_end=config["research_end"],
        data_sources=bundle.source_manifest.to_dict(orient="records"),
        code_commit=_git_revision(),
        metrics=baseline_record["base_metrics"],
        data_gate=gate.to_dict(),
        acceptance=next(row for row in decisions if row["strategy_id"] == "t5_v0_2_baseline"),
        warnings=["Fixed-pool exploratory result; not a strict dynamic-universe backtest."],
    )
    manifest_path = output_dir / "manifests" / f"{manifest.run_id}.json"
    write_immutable_json(manifest_path, manifest)
    return {
        "decision": decision_payload,
        "summary": summary,
        "manifest_path": str(manifest_path),
        "report_path": str(output_dir / "strict_validation_report.md"),
    }
