from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ETF_SYMBOLS = {
    "159516": "sz159516",  # 半导体设备 ETF 国泰
    "513120": "sh513120",  # 港股创新药 ETF 广发
    "159206": "sz159206",  # 卫星 ETF 永赢
    "562500": "sh562500",  # 机器人 ETF 华夏
    "515880": "sh515880",  # 通信 ETF 国泰
    "561380": "sh561380",  # 电网设备 ETF 国泰（截图简称“电网 ETF”）
}

INDEX_SYMBOLS = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
    "科创50": "sh000688",
    "上证50": "sh000016",
    "沪深300": "sh000300",
    "中证500": "sh000905",
    "中证1000": "sh000852",
}

INDEX_SETS = {
    "A_上深创科": ["上证指数", "深证成指", "创业板指", "科创50"],
    "B_上50沪300中500创": ["上证50", "沪深300", "中证500", "创业板指"],
    "C_沪300中500中1000创": ["沪深300", "中证500", "中证1000", "创业板指"],
    "D_上沪300中500创": ["上证指数", "沪深300", "中证500", "创业板指"],
}

SOURCE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SOURCE_NOTE = (
    "Tencent public market-data endpoint; qfq-adjusted daily OHLC when available, "
    "otherwise raw daily OHLC. Downloaded for research reproducibility."
)


@dataclass(frozen=True)
class StrategyConfig:
    momentum_window: int = 15
    top_k: int = 2
    replacement_buffer: float = 0.02
    index_window: int = 60
    min_positive_indices: int = 1
    index_set: str = "A_上深创科"


@dataclass(frozen=True)
class SimulationConfig:
    execution: str = "next_open"
    transaction_cost: float = 0.001
    stop_mode: str = "none"
    hard_stop: float = 0.05
    cooldown_days: int = 1


def _request_json(url: str, retries: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except Exception as exc:  # network failures are retried and surfaced with context
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Market-data request failed after {retries} attempts: {url}") from last_error


def _fetch_chunk(symbol: str, start: str, end: str, limit: int = 640) -> tuple[str, list[list[str]]]:
    parameter = f"{symbol},day,{start},{end},{limit},qfq"
    url = SOURCE_URL + "?" + urllib.parse.urlencode({"param": parameter})
    payload = _request_json(url)
    security = payload["data"][symbol]
    rows = security.get("qfqday") or security.get("day") or []
    name = security.get("qt", {}).get(symbol, [None, symbol])[1]
    return name, rows


def fetch_daily_prices(
    symbol: str,
    start: str,
    end: str,
    cache_dir: str | Path = "data/cache",
    refresh: bool = False,
) -> tuple[str, pd.DataFrame]:
    """Fetch a full daily OHLC history, paginating Tencent's 640-row response limit."""
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    csv_path = cache_path / f"{symbol}_{start}_{end}.csv"
    meta_path = cache_path / f"{symbol}_{start}_{end}.json"

    if csv_path.exists() and meta_path.exists() and not refresh:
        frame = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        return metadata["name"], frame

    all_rows: list[list[str]] = []
    current_end = end
    name = symbol
    while True:
        name, rows = _fetch_chunk(symbol, start, current_end)
        if not rows:
            break
        all_rows = rows + all_rows
        first_date = datetime.strptime(rows[0][0], "%Y-%m-%d")
        if rows[0][0] <= start or len(rows) < 640:
            break
        current_end = (first_date - timedelta(days=1)).strftime("%Y-%m-%d")
        time.sleep(0.05)

    deduplicated = {row[0]: row for row in all_rows}
    rows = [deduplicated[key] for key in sorted(deduplicated) if start <= key <= end]
    if not rows:
        raise ValueError(f"No price rows returned for {symbol} between {start} and {end}")

    frame = pd.DataFrame(
        [row[:6] for row in rows],
        columns=["date", "open", "close", "high", "low", "volume"],
    )
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ["open", "close", "high", "low", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.set_index("date").sort_index()

    frame.reset_index().to_csv(csv_path, index=False, encoding="utf-8-sig")
    meta_path.write_text(
        json.dumps(
            {
                "symbol": symbol,
                "name": name,
                "start": start,
                "end": end,
                "rows": len(frame),
                "source": SOURCE_URL,
                "source_note": SOURCE_NOTE,
                "downloaded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return name, frame


def load_research_data(
    start: str = "2023-01-01",
    end: str = "2026-07-17",
    cache_dir: str | Path = "data/cache",
    refresh: bool = False,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Return individual frames and a traceable source manifest."""
    frames: dict[str, pd.DataFrame] = {}
    records = []
    for label, symbol in {**ETF_SYMBOLS, **INDEX_SYMBOLS}.items():
        name, frame = fetch_daily_prices(symbol, start, end, cache_dir, refresh)
        frames[label] = frame
        records.append(
            {
                "label": label,
                "symbol": symbol,
                "name": name,
                "first_date": frame.index.min().date().isoformat(),
                "last_date": frame.index.max().date().isoformat(),
                "rows": len(frame),
            }
        )
    return frames, pd.DataFrame(records)


def price_matrices(
    frames: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    calendar = frames["上证指数"].index
    asset_open = pd.DataFrame(
        {code: frames[code]["open"].reindex(calendar) for code in ETF_SYMBOLS}
    )
    asset_close = pd.DataFrame(
        {code: frames[code]["close"].reindex(calendar) for code in ETF_SYMBOLS}
    )
    index_close = pd.DataFrame(
        {name: frames[name]["close"].reindex(calendar) for name in INDEX_SYMBOLS}
    )
    return asset_open, asset_close, index_close


def asset_field_matrix(frames: dict[str, pd.DataFrame], field: str) -> pd.DataFrame:
    """Align one ETF OHLCV field to the mainland trading calendar."""
    if field not in {"open", "close", "high", "low", "volume"}:
        raise ValueError(f"Unsupported field: {field}")
    calendar = frames["上证指数"].index
    return pd.DataFrame(
        {code: frames[code][field].reindex(calendar) for code in ETF_SYMBOLS}
    )


def build_target_weights(
    asset_close: pd.DataFrame,
    index_close: pd.DataFrame,
    config: StrategyConfig,
    use_index_filter: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Build point-in-time top-K weights with a replacement hysteresis buffer."""
    momentum = asset_close / asset_close.shift(config.momentum_window) - 1
    if use_index_filter:
        index_columns = INDEX_SETS[config.index_set]
        index_momentum = index_close[index_columns] / index_close[index_columns].shift(config.index_window) - 1
        gate = (index_momentum > 0).sum(axis=1) >= config.min_positive_indices
    else:
        gate = pd.Series(True, index=asset_close.index)

    target_values = np.zeros(asset_close.shape, dtype=float)
    momentum_values = momentum.to_numpy(dtype=float)
    gate_values = gate.to_numpy(dtype=bool)
    held: list[int] = []
    for row_position in range(len(asset_close.index)):
        row_scores = momentum_values[row_position]
        valid_positions = np.flatnonzero(~np.isnan(row_scores))
        if not gate_values[row_position] or valid_positions.size == 0:
            held = []
            continue

        ordered = valid_positions[np.argsort(row_scores[valid_positions])[::-1]].tolist()
        valid_set = set(valid_positions.tolist())
        held = [position for position in held if position in valid_set]
        desired_count = min(config.top_k, len(ordered))
        while len(held) < desired_count:
            addition = next(position for position in ordered if position not in held)
            held.append(addition)

        changed = True
        while changed and held:
            changed = False
            outside = [position for position in ordered if position not in held]
            if not outside:
                break
            weakest = min(held, key=lambda position: row_scores[position])
            challenger = outside[0]
            if row_scores[challenger] > row_scores[weakest] + config.replacement_buffer:
                held.remove(weakest)
                held.append(challenger)
                changed = True

        for column_position in held:
            target_values[row_position, column_position] = 1.0 / len(held)
    target = pd.DataFrame(
        target_values,
        index=asset_close.index,
        columns=asset_close.columns,
    )
    return target, momentum, gate


def _period_setup(
    target: pd.DataFrame,
    asset_open: pd.DataFrame,
    asset_close: pd.DataFrame,
    execution: str,
    asset_execution_price: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if execution == "next_open":
        desired = target.shift(1)
        period_returns = asset_open.shift(-1) / asset_open - 1
    elif execution == "same_close":
        desired = target
        period_returns = asset_close.shift(-1) / asset_close - 1
    elif execution == "next_close":
        desired = target.shift(1)
        period_returns = asset_close.shift(-1) / asset_close - 1
    elif execution == "next_twap_proxy":
        if asset_execution_price is None:
            raise ValueError("asset_execution_price is required for next_twap_proxy")
        desired = target.shift(1)
        period_returns = asset_execution_price.shift(-1) / asset_execution_price - 1
    elif execution == "invalid_same_day":
        desired = target
        period_returns = asset_close / asset_close.shift(1) - 1
    else:
        raise ValueError(f"Unknown execution mode: {execution}")
    return desired.fillna(0.0), period_returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def simulate(
    target: pd.DataFrame,
    asset_open: pd.DataFrame,
    asset_close: pd.DataFrame,
    start: str,
    end: str,
    config: SimulationConfig,
    asset_low: pd.DataFrame | None = None,
    asset_execution_price: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Simulate the strategy with explicit timing, costs, and optional stop behavior."""
    desired_matrix, return_matrix = _period_setup(
        target,
        asset_open,
        asset_close,
        config.execution,
        asset_execution_price=asset_execution_price,
    )
    dates = desired_matrix.index[
        (desired_matrix.index >= pd.Timestamp(start))
        & (desired_matrix.index <= pd.Timestamp(end))
    ]
    dates = dates[:-1]

    if config.stop_mode == "none":
        desired_values = desired_matrix.loc[dates].to_numpy(dtype=float)
        return_values = return_matrix.loc[dates].to_numpy(dtype=float)
        previous_values = np.vstack(
            [np.zeros((1, desired_values.shape[1])), desired_values[:-1]]
        )
        turnover = np.abs(desired_values - previous_values).sum(axis=1)
        costs = np.minimum(0.99, config.transaction_cost * turnover)
        gross_returns = (desired_values * return_values).sum(axis=1)
        equity_values = np.cumprod((1.0 - costs) * (1.0 + gross_returns))
        exposures = np.abs(desired_values).sum(axis=1)

        local_drawdowns = np.zeros(len(dates), dtype=float)
        risk_peak = 1.0
        in_risk_last_period = False
        for position, (equity_value, exposure) in enumerate(zip(equity_values, exposures)):
            in_risk = bool(exposure > 0)
            if in_risk and not in_risk_last_period:
                risk_peak = equity_values[position - 1] if position > 0 else 1.0
            if in_risk:
                risk_peak = max(risk_peak, equity_value)
                local_drawdowns[position] = equity_value / risk_peak - 1.0
            in_risk_last_period = in_risk

        result = pd.DataFrame(
            {
                "equity": equity_values,
                "gross_return": gross_returns,
                "turnover": turnover,
                "cost": costs,
                "exposure": exposures,
                "local_drawdown": local_drawdowns,
                "stop_triggered": False,
            },
            index=dates,
        )
        for column_position, code in enumerate(target.columns):
            result[f"w_{code}"] = desired_values[:, column_position]
        result["drawdown"] = result["equity"] / result["equity"].cummax() - 1.0
        result["net_return"] = result["equity"].pct_change().fillna(
            result["equity"] - 1.0
        )
        return result

    desired_values = desired_matrix.loc[dates].to_numpy(dtype=float)
    return_values = return_matrix.loc[dates].to_numpy(dtype=float)
    date_positions = desired_matrix.index.get_indexer(dates)
    open_values = asset_open.to_numpy(dtype=float)
    close_values = asset_close.to_numpy(dtype=float)
    low_values = asset_low.to_numpy(dtype=float) if asset_low is not None else None
    execution_values = (
        asset_execution_price.to_numpy(dtype=float)
        if asset_execution_price is not None
        else None
    )
    previous_weights = np.zeros(target.shape[1], dtype=float)
    equity = 1.0
    risk_peak = 1.0
    cooldown_remaining = 0
    in_risk_last_period = False
    records = []

    for row_position, date in enumerate(dates):
        desired = desired_values[row_position].copy()
        if config.stop_mode == "cooldown_next_open" and cooldown_remaining > 0:
            desired *= 0.0
            cooldown_remaining -= 1

        in_risk = bool(np.abs(desired).sum() > 0)
        if in_risk and not in_risk_last_period:
            risk_peak = equity

        entry_turnover = float(np.abs(desired - previous_weights).sum())
        turnover = entry_turnover
        cost = min(0.99, config.transaction_cost * entry_turnover)
        equity *= 1.0 - cost
        raw_gross_return = float((desired * return_values[row_position]).sum())
        gross_return = raw_gross_return
        stop_triggered = False
        if config.stop_mode == "exact_daily_loss_cap" and raw_gross_return < -config.hard_stop:
            gross_return = -config.hard_stop
            stop_triggered = True
        elif config.stop_mode == "ohlc_stop":
            if config.execution not in {"same_close", "next_close", "next_twap_proxy"}:
                raise ValueError("ohlc_stop requires close-to-close execution")
            if asset_low is None:
                raise ValueError("asset_low is required for ohlc_stop")
            current_location = date_positions[row_position]
            next_location = current_location + 1
            base_price = (
                execution_values[current_location]
                if config.execution == "next_twap_proxy" and execution_values is not None
                else close_values[current_location]
            )
            portfolio_open_return = float(
                np.nan_to_num(
                    desired * (open_values[next_location] / base_price - 1.0),
                    nan=0.0,
                    posinf=0.0,
                    neginf=0.0,
                ).sum()
            )
            portfolio_low_return = float(
                np.nan_to_num(
                    desired * (low_values[next_location] / base_price - 1.0),
                    nan=0.0,
                    posinf=0.0,
                    neginf=0.0,
                ).sum()
            )
            if portfolio_open_return <= -config.hard_stop:
                gross_return = portfolio_open_return
                stop_triggered = True
            elif portfolio_low_return <= -config.hard_stop:
                gross_return = -config.hard_stop
                stop_triggered = True
        equity *= 1.0 + gross_return

        if stop_triggered and in_risk:
            stop_turnover = float(np.abs(desired).sum())
            turnover += stop_turnover
            stop_cost = min(0.99, config.transaction_cost * stop_turnover)
            equity *= 1.0 - stop_cost
            cost += stop_cost

        if in_risk:
            risk_peak = max(risk_peak, equity)
            local_drawdown = equity / risk_peak - 1.0
        else:
            local_drawdown = 0.0

        if (
            config.stop_mode == "cooldown_next_open"
            and in_risk
            and local_drawdown <= -config.hard_stop
        ):
            stop_triggered = True
            cooldown_remaining = max(config.cooldown_days, 1)

        records.append(
            {
                "date": date,
                "equity": equity,
                "gross_return": gross_return,
                "turnover": turnover,
                "cost": cost,
                "exposure": float(np.abs(desired).sum()),
                "local_drawdown": local_drawdown,
                "stop_triggered": stop_triggered,
                **{
                    f"w_{code}": desired[column_position]
                    for column_position, code in enumerate(target.columns)
                },
            }
        )
        previous_weights = (
            np.zeros(target.shape[1], dtype=float) if stop_triggered else desired
        )
        in_risk_last_period = in_risk and not stop_triggered

    result = pd.DataFrame(records).set_index("date")
    result["drawdown"] = result["equity"] / result["equity"].cummax() - 1.0
    result["net_return"] = result["equity"].pct_change().fillna(result["equity"] - 1.0)
    return result


def performance_metrics(backtest: pd.DataFrame) -> dict[str, float]:
    periods = len(backtest)
    years = periods / 252.0
    ending = float(backtest["equity"].iloc[-1])
    total_return = ending - 1.0
    cagr = ending ** (1.0 / years) - 1.0 if years > 0 else np.nan
    daily_returns = backtest["net_return"].iloc[1:]
    volatility = float(daily_returns.std(ddof=1) * np.sqrt(252))
    sharpe = (
        float(daily_returns.mean() / daily_returns.std(ddof=1) * np.sqrt(252))
        if daily_returns.std(ddof=1) > 0
        else np.nan
    )
    max_drawdown = float(backtest["drawdown"].min())
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else np.nan
    trade_days = int((backtest["turnover"] > 0.05).sum())
    return {
        "ending_equity": ending,
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "total_turnover": float(backtest["turnover"].sum()),
        "annual_turnover": float(backtest["turnover"].sum() / years),
        "trade_days": trade_days,
        "trade_days_per_year": float(trade_days / years),
        "average_exposure": float(backtest["exposure"].mean()),
        "stop_count": int(backtest["stop_triggered"].sum()),
    }


def run_variant(
    asset_open: pd.DataFrame,
    asset_close: pd.DataFrame,
    index_close: pd.DataFrame,
    strategy: StrategyConfig,
    simulation: SimulationConfig,
    start: str,
    end: str,
    use_index_filter: bool = True,
    asset_low: pd.DataFrame | None = None,
    asset_execution_price: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, float], pd.DataFrame, pd.Series]:
    target, momentum, gate = build_target_weights(
        asset_close, index_close, strategy, use_index_filter
    )
    backtest = simulate(
        target,
        asset_open,
        asset_close,
        start,
        end,
        simulation,
        asset_low=asset_low,
        asset_execution_price=asset_execution_price,
    )
    return backtest, performance_metrics(backtest), momentum, gate


def rolling_return_stats(backtest: pd.DataFrame, window: int = 252) -> dict[str, float]:
    rolling = backtest["equity"] / backtest["equity"].shift(window) - 1.0
    rolling = rolling.dropna()
    if rolling.empty:
        return {"count": 0, "worst": np.nan, "median": np.nan, "best": np.nan, "positive_share": np.nan}
    return {
        "count": len(rolling),
        "worst": float(rolling.min()),
        "median": float(rolling.median()),
        "best": float(rolling.max()),
        "positive_share": float((rolling > 0).mean()),
    }


def summarize_variants(rows: Iterable[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    percentage_columns = [
        "total_return",
        "cagr",
        "annual_volatility",
        "max_drawdown",
        "average_exposure",
    ]
    for column in percentage_columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column])
    return frame
