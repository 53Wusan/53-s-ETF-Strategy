from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from app.services.strategy import State, Thresholds, decide


@dataclass
class BacktestResult:
    metrics: dict[str, float]
    equity_curve: pd.DataFrame
    trades: list[dict[str, float | str]]


def _max_drawdown(equity: pd.Series) -> float:
    drawdown = equity / equity.cummax() - 1
    return float(drawdown.min()) if not drawdown.empty else 0.0


def _metrics(equity: pd.Series, trades: list[dict[str, float | str]], turnover: float) -> dict[str, float]:
    if len(equity) < 2:
        return {"total_return": 0, "cagr": 0, "max_drawdown": 0, "sharpe": 0, "calmar": 0, "trades": 0, "turnover": 0, "win_rate": 0}
    daily = equity.pct_change().dropna()
    years = max(len(equity) / 252, 1 / 252)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)
    max_drawdown = _max_drawdown(equity)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    exits = [trade for trade in trades if trade["side"] == "sell"]
    winners = [trade for trade in exits if float(trade.get("realized_pnl", 0)) > 0]
    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "calmar": calmar,
        "trades": float(len(trades)),
        "turnover": float(turnover),
        "win_rate": float(len(winners) / len(exits)) if exits else 0.0,
        "positive_days": float((daily > 0).mean()) if len(daily) else 0.0,
    }


def run_backtest(frame: pd.DataFrame, thresholds: Thresholds, friction_bps: float = 15) -> BacktestResult:
    data = frame.dropna(subset=["open", "close", "score"]).sort_index()
    if len(data) < 3:
        return BacktestResult({}, pd.DataFrame(), [])
    cash = 1.0
    units = 0.0
    cost_basis = 0.0
    pending_delta = 0
    state = State()
    trades: list[dict[str, float | str]] = []
    equity_rows: list[dict[str, float]] = []
    turnover = 0.0
    previous_score = float(data.iloc[0].score)
    friction = friction_bps / 10_000

    for index, row in data.iterrows():
        open_price = float(row.get("execution_open", row.open))
        if pending_delta:
            equity_open = cash + units * open_price
            target_fraction = state.position_steps / 3
            target_value = equity_open * target_fraction
            current_value = units * open_price
            trade_value = target_value - current_value
            cost = abs(trade_value) * friction
            units_before = units
            realized_pnl = 0.0
            if trade_value > 0:
                cost_basis += trade_value + cost
            elif units_before > 0:
                sold_fraction = min(1.0, abs(trade_value / open_price) / units_before)
                allocated_basis = cost_basis * sold_fraction
                realized_pnl = abs(trade_value) - cost - allocated_basis
                cost_basis -= allocated_basis
            cash -= trade_value + cost
            units += trade_value / open_price
            turnover += abs(trade_value)
            trades.append(
                {
                    "date": str(index),
                    "side": "buy" if trade_value > 0 else "sell",
                    "value": abs(trade_value),
                    "price": open_price,
                    "cost": cost,
                    "realized_pnl": realized_pnl,
                }
            )
            pending_delta = 0
        equity_close = cash + units * float(row.get("execution_close", row.close))
        equity_rows.append(
            {
                "date": index,
                "equity": equity_close,
                "position": state.position_steps / 3,
                "score": float(row.score),
            }
        )
        decision = decide(previous_score, float(row.score), thresholds, state)
        pending_delta = decision.delta
        previous_score = float(row.score)

    equity_curve = pd.DataFrame(equity_rows).set_index("date")
    equity_curve["buy_hold"] = data.loc[equity_curve.index, "adjusted_close"] / float(
        data.loc[equity_curve.index[0], "adjusted_close"]
    )
    if "underlying_adjusted_close" in data:
        underlying = data.loc[equity_curve.index, "underlying_adjusted_close"]
        equity_curve["underlying_buy_hold"] = underlying / float(underlying.iloc[0])
    else:
        equity_curve["underlying_buy_hold"] = 1.0
    equity_curve["cash"] = 1.0
    return BacktestResult(_metrics(equity_curve.equity, trades, turnover), equity_curve, trades)


def calibrate_thresholds(frame: pd.DataFrame) -> tuple[Thresholds, str, dict[str, float]]:
    data = frame.dropna(subset=["score", "open", "close"]).copy()
    if len(data) < 504:
        return Thresholds(), "low", {"reason": "少于 504 个有效交易日，使用 ±60 回退线"}
    split = int(len(data) * 0.8)
    training = data.iloc[:split]
    validation = data.iloc[split:]
    fold_indices = np.array_split(np.arange(len(training)), 3)
    folds = [training.iloc[indices] for indices in fold_indices if len(indices) >= 100]
    best: tuple[float, Thresholds, dict[str, float]] | None = None
    for buy_1 in range(-45, -81, -5):
        buys = (float(buy_1), float(max(-95, buy_1 - 15)), float(max(-95, buy_1 - 30)))
        for sell_1 in range(45, 81, 5):
            sells = (float(sell_1), float(min(95, sell_1 + 15)), float(min(95, sell_1 + 30)))
            thresholds = Thresholds(buys=buys, sells=sells)
            results = [
                run_backtest(fold, thresholds, friction).metrics
                for fold in folds
                for friction in (5, 15, 30)
            ]
            if sum(result.get("trades", 0) for result in results) < 6:
                continue
            calmars = [result.get("calmar", 0) for result in results]
            sharpes = [result.get("sharpe", 0) for result in results]
            turnovers = [result.get("turnover", 0) for result in results]
            score = float(np.median(calmars) + 0.25 * np.median(sharpes) - 0.02 * np.median(turnovers))
            if min(calmars) <= 0:
                continue
            metrics = {"training_robust_score": score}
            if best is None or score > best[0]:
                best = (score, thresholds, metrics)
    if best is None:
        return Thresholds(), "low", {"reason": "样本外没有稳定参数，使用 ±60 回退线"}
    holdout = [run_backtest(validation, best[1], friction).metrics for friction in (5, 15, 30)]
    holdout_trades = sum(result.get("trades", 0) for result in holdout)
    holdout_returns = [result.get("total_return", 0) for result in holdout]
    if holdout_trades < 1 or float(np.median(holdout_returns)) <= 0:
        return Thresholds(), "low", {
            "reason": "最终留出段未通过收益与交易覆盖门槛，使用 ±60 回退线",
            "holdout_trades": holdout_trades,
            "holdout_median_return": float(np.median(holdout_returns)),
        }
    metrics = dict(best[2])
    metrics.update(
        {
            "holdout_trades": holdout_trades,
            "holdout_median_return": float(np.median(holdout_returns)),
            "holdout_median_calmar": float(np.median([row.get("calmar", 0) for row in holdout])),
        }
    )
    confidence = "high" if holdout_trades >= 6 and metrics["holdout_median_calmar"] >= 0.5 else "medium"
    return best[1], confidence, metrics


def thresholds_as_dict(thresholds: Thresholds) -> dict[str, tuple[float, float, float]]:
    return asdict(thresholds)
