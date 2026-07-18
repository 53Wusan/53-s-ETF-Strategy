from __future__ import annotations

import json
from pathlib import Path

import nbformat as nbf
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "v0_2"
NOTEBOOK_PATH = ROOT / "notebooks" / "02_t5_strict_validation.ipynb"


def markdown(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


def main() -> None:
    decision = json.loads((OUTPUT_DIR / "decision.json").read_text(encoding="utf-8"))
    summary = pd.read_csv(OUTPUT_DIR / "strategy_summary.csv")
    baseline = summary[(summary.strategy_id == "t5_v0_2_baseline") & (summary.scenario == "base")].iloc[0]
    volatility = summary[(summary.strategy_id == "t5_volatility_control_30") & (summary.scenario == "base")].iloc[0]
    cells = [
        markdown(
            """
# Money Back V0.2：T5 严格验证

本笔记是 `v0.2-strict-research` 的可重复审计入口。它只读取研究内核生成的有版本结果，不在笔记中重新定义策略。

结论不构成投资建议或实盘授权。
"""
        ),
        markdown("## tl;dr"),
        markdown(
            f"""
- **决策：{decision['decision']}。** 免费数据未通过时点一致 ETF 名册、可信成交额和独立第二行情源三项闸门。
- V0.1 冻结回归仍为 **{decision['v0_1_regression']['ending_equity']:.2f} 倍**，最大回撤 **{decision['v0_1_regression']['max_drawdown']:.1%}**。
- V0.2 固定池 T5 的滚动三年中位数约 **{baseline['median_multiple']:.2f} 倍**，最大回撤 **{baseline['max_drawdown']:.1%}**。
- 波动控制版最大回撤降至 **{volatility['max_drawdown']:.1%}**，但滚动三年中位数只有 **{volatility['median_multiple']:.2f} 倍**，仍未达到 4 倍目标。
"""
        ),
        markdown(
            """
## Context & Methods

### Key Assumptions

- 资产边界：境内股票型宽基、行业和主题 ETF，加现金；跨境 ETF 只保留在 V0.1 重建回归中。
- 信号：复权收盘；基准执行：次日 OHLC4/TWAP 代理、单边 10bp。
- 压力执行：信号延迟到第二个开盘、单边 20bp。
- 固定池性能从至少两只境内 ETF 已上市 120 个交易日时开始。
- 只有数据闸门和性能门槛同时通过，才允许进入 12 周纸面跟踪。
"""
        ),
        code(
            """
from pathlib import Path
import json
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import Markdown, display

ROOT = Path.cwd()
OUTPUT_DIR = ROOT / "outputs" / "v0_2"
summary = pd.read_csv(OUTPUT_DIR / "strategy_summary.csv")
rolling = pd.read_csv(OUTPUT_DIR / "rolling_3y_multiples.csv", parse_dates=["date"])
sources = pd.read_csv(OUTPUT_DIR / "source_manifest.csv")
issues = pd.read_csv(OUTPUT_DIR / "data_quality_issues.csv")
decision = json.loads((OUTPUT_DIR / "decision.json").read_text(encoding="utf-8"))
"""
        ),
        markdown("## Data"),
        code(
            """
display(Markdown(f"**数据闸门：{decision['data_gate']['status']}。** 当前结果只能标记为固定池探索。"))
display(sources.groupby(["label", "series"], as_index=False).agg(
    first_date=("first_date", "min"), last_date=("last_date", "max"), rows=("rows", "max")
))
display(issues[["code", "severity", "message", "symbol", "date"]].head(20))
"""
        ),
        markdown("## Results"),
        code(
            """
focus_ids = [
    "t5_v0_2_baseline",
    "t5_volatility_control_30",
    "challenger_a_dual_momentum",
    "challenger_b_vol_adjusted_trend",
]
focus = summary[(summary.strategy_id.isin(focus_ids)) & (summary.scenario == "base")].copy()
display(focus[["strategy_id", "ending_equity", "cagr", "max_drawdown", "median_multiple", "p25_multiple", "worst_multiple", "trade_days_per_year"]])

plt.style.use("seaborn-v0_8-whitegrid")
fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
colors = ["#2563EB", "#D97706", "#6B7280", "#9CA3AF"]
axes[0].barh(focus.strategy_id, focus.median_multiple, color=colors)
axes[0].axvline(4.0, color="#111827", linestyle="--", linewidth=1.5, label="4.0x gate")
axes[0].set_title("Rolling Three-Year Median Multiple")
axes[0].set_xlabel("Wealth multiple")
axes[0].legend(frameon=False)
axes[1].barh(focus.strategy_id, focus.max_drawdown.abs(), color=colors)
axes[1].axvline(0.40, color="#111827", linestyle="--", linewidth=1.5, label="40% gate")
axes[1].set_title("Maximum Drawdown")
axes[1].set_xlabel("Absolute drawdown")
axes[1].xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
axes[1].legend(frameon=False)
fig.suptitle("Money Back V0.2 Performance Gates", x=0.08, ha="left", fontsize=15, weight="bold")
fig.text(0.08, 0.92, "Fixed-pool exploratory evidence; not a point-in-time full-market backtest", color="#4B5563")
fig.tight_layout(rect=[0, 0, 1, 0.89])
comparison_path = OUTPUT_DIR / "performance_gate_comparison.png"
fig.savefig(comparison_path, dpi=180, bbox_inches="tight")
plt.show()
"""
        ),
        markdown("## Limitations, uncertainty, and robustness"),
        code(
            """
selected = rolling[(rolling.scenario == "base") & rolling.strategy_id.isin(["t5_v0_2_baseline", "t5_volatility_control_30"])]
groups = [group.multiple.to_numpy() for _, group in selected.groupby("strategy_id")]
labels = [name for name, _ in selected.groupby("strategy_id")]
fig, ax = plt.subplots(figsize=(9, 5.5))
ax.boxplot(groups, tick_labels=labels, showfliers=False)
ax.axhline(4.0, color="#111827", linestyle="--", linewidth=1.5, label="4.0x median target")
ax.axhline(2.0, color="#6B7280", linestyle=":", linewidth=1.5, label="2.0x p25 target")
ax.set_title("Rolling Three-Year Wealth-Multiple Distribution")
ax.set_ylabel("Wealth multiple")
ax.legend(frameon=False)
fig.tight_layout()
distribution_path = OUTPUT_DIR / "rolling_3y_distribution.png"
fig.savefig(distribution_path, dpi=180, bbox_inches="tight")
plt.show()

display(Markdown(
    "The distributions are descriptive only. The six-product fixed pool omits historical delistings and most ETFs that existed before these products launched."
))
"""
        ),
        markdown(
            """
## Takeaways

1. V0.1 已被新内核精确复现，重构没有改写已冻结结论。
2. 严格数据闸门未通过，所以任何收益数字都不能升级为全市场证据。
3. 在可运行的固定池范围内，T5 与波动控制版都未达到滚动三年中位 4 倍。
4. 波动控制降低了回撤，却没有创造足够的收益补偿；这正说明不能只围绕止损继续调参。
5. 当前正确动作是停止策略扩搜，先解决历史退市名册、成交额和第二行情源。

## Further questions

- 能否以免费方式获得 2013 年以来包含退市状态的 ETF 主数据？
- 第二行情源能否在复权因子、停牌和异常跳变上与当前来源独立核对？
"""
        ),
    ]
    notebook = nbf.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.14"},
        },
    )
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(notebook, NOTEBOOK_PATH)
    print(NOTEBOOK_PATH)


if __name__ == "__main__":
    main()
