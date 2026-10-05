from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    DailyBar,
    FxRate,
    Instrument,
    JobRun,
    Market,
    PortfolioKind,
    QualityStatus,
    SignalAction,
    SignalSnapshot,
    StrategyRun,
    StrategyState,
    ThresholdProfile,
    Trade,
    TradeSide,
)
from app.services.backtest import calibrate_thresholds, run_backtest
from app.services.indicators import compute_factors
from app.services.market_data import MarketDataError, fetch_with_validation, upsert_bars
from app.services.notifications import send_error, send_once, signal_card
from app.services.portfolio import open_quantity
from app.services.strategy import State, Thresholds, decide


def _frame_from_bars(db: Session, instrument_id: int) -> pd.DataFrame:
    bars = list(
        db.scalars(
            select(DailyBar)
            .where(DailyBar.instrument_id == instrument_id)
            .order_by(DailyBar.date)
        )
    )
    if not bars:
        return pd.DataFrame()
    frame = pd.DataFrame(
        [
            {
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close,
                "volume": bar.volume,
                "source": bar.source,
            }
            for bar in bars
        ]
    )
    # Prefer Yahoo for a date, but remain operational when the explicit Stooq fallback is used.
    frame["source_priority"] = frame["source"].map({"yahoo": 0, "stooq": 1}).fillna(2)
    return frame.sort_values(["date", "source_priority"]).drop_duplicates("date").set_index("date").drop(columns=["source_priority"], errors="ignore")


def _active_profile(db: Session, instrument_id: int) -> ThresholdProfile:
    profile = db.scalar(
        select(ThresholdProfile)
        .where(ThresholdProfile.instrument_id == instrument_id, ThresholdProfile.active.is_(True))
        .order_by(desc(ThresholdProfile.created_at))
        .limit(1)
    )
    if profile is None:
        profile = ThresholdProfile(instrument_id=instrument_id)
        db.add(profile)
        db.flush()
    return profile


def _profile_thresholds(profile: ThresholdProfile) -> Thresholds:
    return Thresholds(
        buys=(profile.buy_1, profile.buy_2, profile.buy_3),
        sells=(profile.sell_1, profile.sell_2, profile.sell_3),
    )


def _calibrate(db: Session, instrument: Instrument, factors: pd.DataFrame) -> ThresholdProfile:
    current = _active_profile(db, instrument.id)
    age = datetime.now(timezone.utc) - current.created_at.replace(tzinfo=current.created_at.tzinfo or timezone.utc)
    if current.method != "fallback" and age.days < 30:
        return current
    thresholds, confidence, metrics = calibrate_thresholds(factors)
    current.active = False
    profile = ThresholdProfile(
        instrument_id=instrument.id,
        buy_1=thresholds.buys[0],
        buy_2=thresholds.buys[1],
        buy_3=thresholds.buys[2],
        sell_1=thresholds.sells[0],
        sell_2=thresholds.sells[1],
        sell_3=thresholds.sells[2],
        confidence=confidence,
        method="walk_forward_calmar" if confidence != "low" else "fallback",
        train_start=factors.index[0],
        train_end=factors.index[-1],
        validation_metrics=metrics,
    )
    db.add(profile)
    db.flush()
    return profile


def _save_backtest(db: Session, instrument: Instrument, factors: pd.DataFrame, profile: ThresholdProfile) -> None:
    result = run_backtest(factors, _profile_thresholds(profile), friction_bps=15)
    if result.equity_curve.empty:
        return
    curve = [
        {
            "date": str(index),
            "equity": round(float(row.equity), 6),
            "buy_hold": round(float(row.buy_hold), 6),
            "underlying_buy_hold": round(float(row.underlying_buy_hold), 6),
            "cash": round(float(row.cash), 6),
            "position": round(float(row.position), 4),
        }
        for index, row in result.equity_curve.iterrows()
    ]
    db.add(
        StrategyRun(
            instrument_id=instrument.id,
            start_date=result.equity_curve.index[0],
            end_date=result.equity_curve.index[-1],
            friction_bps=15,
            parameters={
                "buys": list(_profile_thresholds(profile).buys),
                "sells": list(_profile_thresholds(profile).sells),
                "execution": "next_open",
            },
            metrics=result.metrics,
            equity_curve=curve,
        )
    )


def _paper_state(db: Session, instrument_id: int) -> StrategyState:
    state = db.scalar(
        select(StrategyState).where(
            StrategyState.instrument_id == instrument_id,
            StrategyState.portfolio_kind == PortfolioKind.PAPER,
        )
    )
    if state is None:
        state = StrategyState(instrument_id=instrument_id, portfolio_kind=PortfolioKind.PAPER)
        db.add(state)
        db.flush()
    return state


def _fill_pending(db: Session, instrument: Instrument, state: StrategyState, bar_date: date, open_price: float) -> None:
    if not state.pending_delta or not state.pending_signal_date or bar_date <= state.pending_signal_date:
        return
    delta = state.pending_delta
    fee_rate = Decimal("0.0015")
    if delta > 0:
        value = Decimal(instrument.strategy_capital) * Decimal(delta) / Decimal(3)
        quantity = value / Decimal(str(open_price))
        side = TradeSide.BUY
    else:
        current_quantity = open_quantity(db, instrument.id, PortfolioKind.PAPER)
        if state.position_steps <= 0 or current_quantity <= 0:
            state.pending_delta = 0
            state.pending_signal_id = None
            state.pending_signal_date = None
            return
        quantity = current_quantity * Decimal(abs(delta)) / Decimal(state.position_steps)
        value = quantity * Decimal(str(open_price))
        side = TradeSide.SELL
    db.add(
        Trade(
            instrument_id=instrument.id,
            portfolio_kind=PortfolioKind.PAPER,
            side=side,
            quantity=quantity,
            price=Decimal(str(open_price)),
            fee=value * fee_rate,
            currency=instrument.currency,
            executed_at=datetime.combine(bar_date, datetime.min.time(), tzinfo=timezone.utc),
            note="策略信号次一交易日开盘模拟成交",
            source="strategy",
            signal_snapshot_id=state.pending_signal_id,
        )
    )
    state.position_steps = max(0, min(3, state.position_steps + delta))
    state.pending_delta = 0
    state.pending_signal_id = None
    state.pending_signal_date = None
    if state.position_steps == 0:
        state.cycle_id += 1
        state.buy_mask = 0
        state.sell_mask = 0
    db.flush()


def _store_signal(
    db: Session,
    instrument: Instrument,
    factors: pd.DataFrame,
    profile: ThresholdProfile,
    quality_status: QualityStatus,
) -> SignalSnapshot:
    latest = factors.iloc[-1]
    latest_date = factors.index[-1]
    existing = db.scalar(
        select(SignalSnapshot).where(
            SignalSnapshot.instrument_id == instrument.id,
            SignalSnapshot.date == latest_date,
        )
    )
    if existing:
        return existing
    state_model = _paper_state(db, instrument.id)
    _fill_pending(db, instrument, state_model, latest_date, float(latest.open))
    previous = db.scalar(
        select(SignalSnapshot)
        .where(SignalSnapshot.instrument_id == instrument.id, SignalSnapshot.date < latest_date)
        .order_by(desc(SignalSnapshot.date))
        .limit(1)
    )
    prev_score = previous.score if previous else float(latest.score)
    calculation_state = State(state_model.position_steps, state_model.buy_mask, state_model.sell_mask)
    if state_model.pending_delta:
        decision_action, decision_delta, decision_reason = SignalAction.HOLD, 0, "等待上一信号在下一交易日开盘成交"
    else:
        decision = decide(prev_score, float(latest.score), _profile_thresholds(profile), calculation_state)
        decision_action, decision_delta, decision_reason = decision.action, decision.delta, decision.reason
        state_model.buy_mask = calculation_state.buy_mask
        state_model.sell_mask = calculation_state.sell_mask
    snapshot = SignalSnapshot(
        instrument_id=instrument.id,
        date=latest_date,
        price=float(latest.close),
        market_position=float(latest.market_position),
        etf_position=float(latest.etf_position),
        volatility=float(latest.volatility),
        trend=float(latest.trend),
        score=float(latest.score),
        action=decision_action,
        target_step_delta=decision_delta,
        confidence=profile.confidence,
        quality_status=quality_status,
        reason=decision_reason,
        threshold_profile_id=profile.id,
    )
    db.add(snapshot)
    db.flush()
    if decision_delta:
        state_model.pending_delta = decision_delta
        state_model.pending_signal_id = snapshot.id
        state_model.pending_signal_date = latest_date
        settings = get_settings()
        payload = signal_card(
            instrument.symbol,
            decision_action.value,
            snapshot.score,
            snapshot.price,
            snapshot.reason,
            profile.confidence,
            f"{settings.public_base_url}/instruments/{instrument.symbol}",
        )
        send_once(db, f"signal:{instrument.symbol}:{latest_date}:{decision_action.value}", "signal", payload)
    return snapshot


def _store_blocked_signal(
    db: Session,
    instrument: Instrument,
    signal_date: date,
    price: float,
    reason: str,
) -> SignalSnapshot:
    existing = db.scalar(
        select(SignalSnapshot).where(
            SignalSnapshot.instrument_id == instrument.id,
            SignalSnapshot.date == signal_date,
        )
    )
    previous = db.scalar(
        select(SignalSnapshot)
        .where(SignalSnapshot.instrument_id == instrument.id)
        .order_by(desc(SignalSnapshot.date))
        .limit(1)
    )
    values = {
        "price": price,
        "market_position": previous.market_position if previous else 0,
        "etf_position": previous.etf_position if previous else 0,
        "volatility": previous.volatility if previous else 0,
        "trend": previous.trend if previous else 0,
        "score": previous.score if previous else 0,
        "action": SignalAction.DATA_BLOCKED,
        "target_step_delta": 0,
        "confidence": "blocked",
        "quality_status": QualityStatus.BLOCKED,
        "reason": reason,
    }
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        return existing
    snapshot = SignalSnapshot(instrument_id=instrument.id, date=signal_date, **values)
    db.add(snapshot)
    db.flush()
    return snapshot


def process_instrument(db: Session, instrument: Instrument, end: date | None = None) -> dict:
    settings = get_settings()
    end = end or date.today()
    start = end - timedelta(days=365 * settings.market_data_lookback_years)
    etf_frame, source, quality = fetch_with_validation(instrument.yahoo_symbol, start, end)
    upsert_bars(db, instrument, etf_frame, source, quality)
    if quality.status == QualityStatus.BLOCKED:
        _store_blocked_signal(
            db,
            instrument,
            etf_frame.index[-1],
            float(etf_frame.iloc[-1].close),
            "；".join(quality.messages),
        )
        db.commit()
        send_error(db, f"data:{instrument.symbol}:{end}", f"{instrument.symbol} 行情被阻断", "；".join(quality.messages))
        return {"symbol": instrument.symbol, "status": "blocked", "messages": quality.messages}
    underlying_frame, _, underlying_quality = fetch_with_validation(
        instrument.underlying_symbol, start, end, use_fallback=instrument.market == Market.US
    )
    if underlying_quality.status == QualityStatus.BLOCKED:
        _store_blocked_signal(
            db,
            instrument,
            etf_frame.index[-1],
            float(etf_frame.iloc[-1].close),
            "基础指数：" + "；".join(underlying_quality.messages),
        )
        db.commit()
        send_error(db, f"underlying:{instrument.symbol}:{end}", f"{instrument.symbol} 基准行情被阻断", "；".join(underlying_quality.messages))
        return {"symbol": instrument.symbol, "status": "blocked", "messages": underlying_quality.messages}
    stored = _frame_from_bars(db, instrument.id)
    factors = compute_factors(stored, underlying_frame)
    if len(factors) < 100:
        raise MarketDataError(f"{instrument.symbol} 有效指标历史不足 100 日")
    profile = _calibrate(db, instrument, factors)
    _save_backtest(db, instrument, factors, profile)
    snapshot = _store_signal(db, instrument, factors, profile, quality.status)
    db.commit()
    return {
        "symbol": instrument.symbol,
        "status": "ok",
        "date": str(snapshot.date),
        "score": snapshot.score,
        "action": snapshot.action.value,
        "quality_messages": quality.messages,
    }


def refresh_fx_rates(db: Session, end: date | None = None) -> None:
    end = end or date.today()
    start = end - timedelta(days=14)
    for base in ("USD", "HKD"):
        symbol = f"{base}CNY=X"
        try:
            frame, _, quality = fetch_with_validation(symbol, start, end, use_fallback=False)
            if quality.status == QualityStatus.BLOCKED:
                continue
            for index, row in frame.iterrows():
                existing = db.scalar(select(FxRate).where(FxRate.date == index, FxRate.base == base, FxRate.quote == "CNY"))
                if existing:
                    existing.rate = float(row.close)
                else:
                    db.add(FxRate(date=index, base=base, quote="CNY", rate=float(row.close)))
        except Exception:
            continue
    db.commit()


def run_market_job(market: Market) -> dict:
    with SessionLocal() as db:
        run = JobRun(job_name="market_recompute", market=market.value)
        db.add(run)
        db.commit()
        results: list[dict] = []
        try:
            instruments = list(db.scalars(select(Instrument).where(Instrument.enabled.is_(True), Instrument.market == market)))
            for instrument in instruments:
                try:
                    results.append(process_instrument(db, instrument))
                except Exception as exc:
                    db.rollback()
                    results.append({"symbol": instrument.symbol, "status": "error", "error": str(exc)})
                    send_error(db, f"job:{instrument.symbol}:{date.today()}", f"{instrument.symbol} 每日任务失败", str(exc))
            refresh_fx_rates(db)
            run.status = "completed"
            run.detail = {"results": results}
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return run.detail
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise


def run_all_markets() -> dict:
    return {market.value: run_market_job(market) for market in (Market.HK, Market.US)}


def backup_database() -> dict:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        return {"status": "skipped", "reason": "SQLite 开发环境请直接备份数据库文件"}
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = backup_dir / f"leveraged-etf-{stamp}.dump"
    env = {"PGPASSWORD": settings.postgres_password}
    subprocess.run(
        [
            "pg_dump",
            "-Fc",
            "-h",
            settings.postgres_host,
            "-p",
            str(settings.postgres_port),
            "-U",
            settings.postgres_user,
            "-d",
            settings.postgres_db,
            "-f",
            str(output),
        ],
        check=True,
        env={**__import__("os").environ, **env},
    )
    files = sorted(backup_dir.glob("leveraged-etf-*.dump"), reverse=True)
    keep = set(files[:7])
    weekly: dict[str, Path] = {}
    for path in files:
        week = datetime.strptime(path.stem.split("-")[2], "%Y%m%d").strftime("%G-%V")
        weekly.setdefault(week, path)
    keep.update(list(weekly.values())[:3])
    for path in files:
        if path not in keep:
            path.unlink()
    return {"status": "ok", "file": str(output), "retained": len(keep)}
