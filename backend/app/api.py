from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.auth import create_token, current_user, verify_login
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    DailyBar,
    Instrument,
    PortfolioKind,
    SignalSnapshot,
    StrategyRun,
    StrategyState,
    ThresholdProfile,
    Trade,
    TradeSide,
)
from app.schemas import LoginRequest, TradeCreate, TradeOut, TradeUpdate
from app.services.execution_research import PROFILE_IDS
from app.services.execution_research import dashboard as execution_dashboard
from app.services.execution_research import history_view as execution_history
from app.services.execution_research import result_bundle as execution_result
from app.services.jobs import run_all_markets
from app.services.paper_ledger import record_available as record_paper
from app.services.paper_ledger import status as paper_status
from app.services.portfolio import open_quantity, portfolio_snapshot
from app.services.research_cockpit import catalog as research_catalog
from app.services.research_cockpit import compare as research_compare
from app.services.research_cockpit import indicator_history as research_history
from app.services.research_data_refresh import refresh as refresh_research_data

router = APIRouter(prefix="/api")


@router.get("/desk/strategies", dependencies=[Depends(current_user)])
def desk_strategies_endpoint() -> dict:
    from app.services.strategy_desk import curated_strategies
    try:
        return curated_strategies()
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "保留方案尚未生成") from exc


@router.get("/desk/strategies/{identifier}", dependencies=[Depends(current_user)])
def desk_strategy_endpoint(identifier: str) -> dict:
    from app.services.strategy_desk import strategy_detail
    try:
        return strategy_detail(identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, "方案详情尚未生成") from exc


@router.get("/desk/observation/{symbol}", dependencies=[Depends(current_user)])
def desk_observation_endpoint(symbol: str) -> dict:
    from app.services.strategy_desk import observation_summary
    try:
        return observation_summary(symbol.upper())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/execution/catalog", dependencies=[Depends(current_user)])
def execution_catalog_endpoint(profile: str = "near_best") -> dict:
    if profile not in PROFILE_IDS:
        raise HTTPException(422, "未知方案")
    return execution_dashboard(profile)


@router.get("/execution/history/{symbol}", dependencies=[Depends(current_user)])
def execution_history_endpoint(symbol: str, limit: int = 600) -> dict:
    if not 0 <= limit <= 5000:
        raise HTTPException(422, "窗口须在 0 至 5000 个交易日内，0 表示全部")
    try:
        return execution_history(symbol.upper(), limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/execution/results", dependencies=[Depends(current_user)])
def execution_results_endpoint(profile: str = "near_best") -> dict:
    if profile not in PROFILE_IDS:
        raise HTTPException(422, "未知方案")
    try:
        result = execution_result()
        profiles = result.get("profiles", {"near_best": result["selected"]})
        selected = profiles[profile]
        return {
            "profile": profile,
            "search": result["search"],
            "assumptions": result["assumptions"],
            "profiles": {
                k: {
                    "rule": v["rule"],
                    "metrics": v["metrics"],
                    "annual": v["annual"],
                    "stress2022": v.get("stress2022"),
                }
                for k, v in profiles.items()
            },
            "rule": selected["rule"],
            "metrics": selected["metrics"],
            "annual": selected["annual"],
            "trades": selected["trades"],
            "start": selected["start"],
            "end": selected["end"],
            "curve": [
                {"date": d["date"], "equity_hkd": d["equity_hkd"], "cash_hkd": d["cash_hkd"]}
                for d in selected["daily"]
            ],
            "latest_positions": selected["daily"][-1]["positions"],
            "earliest_annual": result.get("earliest_annual", []),
            "tolerance_5": result.get("tolerance_5"),
        }
    except (ValueError, KeyError) as exc:
        raise HTTPException(503, "执行研究结果尚未生成") from exc


@router.get("/execution/export", dependencies=[Depends(current_user)])
def execution_export_endpoint(kind: str = "trades", profile: str = "near_best") -> Response:
    if kind not in ("trades", "annual") or profile not in PROFILE_IDS:
        raise HTTPException(422, "未知导出类型或方案")
    try:
        result = execution_result()
        rows = result["profiles"][profile][kind]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                for k, v in row.items()
            }
            for row in rows
        )
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{profile}_{kind}.csv"'},
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(503, "结果尚未生成") from exc


@router.post("/execution/refresh", dependencies=[Depends(current_user)])
def execution_refresh_endpoint(db: Session = Depends(get_db)) -> dict:
    from app.services.execution_data_refresh import refresh as refresh_execution_data
    from app.services.market_data import MarketDataError

    try:
        result = refresh_execution_data()
        from app.services.live_quote_refresh import sync_local_quotes
        sync_local_quotes(db)
        return result
    except (ValueError, MarketDataError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/research/catalog", dependencies=[Depends(current_user)])
def research_catalog_endpoint() -> dict:
    return research_catalog()


@router.get("/research/paper", dependencies=[Depends(current_user)])
def research_paper_endpoint() -> dict:
    try:
        return paper_status()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/research/paper/record", dependencies=[Depends(current_user)])
def research_paper_record_endpoint() -> dict:
    try:
        return record_paper()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/research/refresh", dependencies=[Depends(current_user)])
def research_refresh_endpoint() -> dict:
    try:
        result = refresh_research_data()
        result["paper"] = record_paper()
        return result
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/research/history/{symbol}", dependencies=[Depends(current_user)])
def research_history_endpoint(symbol: str) -> dict:
    try:
        return research_history(symbol.upper())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/research/compare", dependencies=[Depends(current_user)])
def research_compare_endpoint(symbols: str, start: date, end: date) -> dict:
    try:
        return research_compare(
            tuple(part.strip().upper() for part in symbols.split(",")), str(start), str(end)
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@router.post("/auth/login")
def login(
    payload: LoginRequest, response: Response, settings: Settings = Depends(get_settings)
) -> dict:
    if not verify_login(payload.username, payload.password, settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_token(payload.username, settings)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        max_age=24 * 60 * 60,
    )
    return {"username": payload.username}


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/auth/me")
def me(user: str = Depends(current_user)) -> dict:
    return {"username": user}


def _threshold_dict(profile: ThresholdProfile | None) -> dict:
    if not profile:
        return {
            "buys": [-60, -75, -90],
            "sells": [60, 75, 90],
            "confidence": "low",
            "method": "fallback",
        }
    return {
        "buys": [profile.buy_1, profile.buy_2, profile.buy_3],
        "sells": [profile.sell_1, profile.sell_2, profile.sell_3],
        "confidence": profile.confidence,
        "method": profile.method,
        "validation_metrics": profile.validation_metrics,
    }


@router.get("/instruments", dependencies=[Depends(current_user)])
def instruments(db: Session = Depends(get_db)) -> list[dict]:
    result: list[dict] = []
    today = date.today()
    for instrument in db.scalars(select(Instrument).order_by(Instrument.market, Instrument.symbol)):
        latest = db.scalar(
            select(DailyBar)
            .where(DailyBar.instrument_id == instrument.id)
            .order_by(desc(DailyBar.date))
            .limit(1)
        )
        age = (today - latest.date).days if latest else None
        result.append(
            {
                "id": instrument.id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "market": instrument.market.value,
                "currency": instrument.currency,
                "leverage": instrument.leverage,
                "underlying_symbol": instrument.underlying_symbol,
                "underlying_name": instrument.underlying_name,
                "enabled": instrument.enabled,
                "strategy_capital": float(instrument.strategy_capital),
                "latest_bar_date": str(latest.date) if latest else None,
                "data_status": "missing"
                if not latest
                else "stale"
                if age is not None and age > 5
                else latest.quality_status.value,
            }
        )
    return result


@router.get("/signals/latest", dependencies=[Depends(current_user)])
def latest_signals(db: Session = Depends(get_db)) -> list[dict]:
    payload: list[dict] = []
    for instrument in db.scalars(
        select(Instrument)
        .where(Instrument.enabled.is_(True))
        .order_by(Instrument.market, Instrument.symbol)
    ):
        signal = db.scalar(
            select(SignalSnapshot)
            .where(SignalSnapshot.instrument_id == instrument.id)
            .order_by(desc(SignalSnapshot.date))
            .limit(1)
        )
        profile = db.scalar(
            select(ThresholdProfile)
            .where(
                ThresholdProfile.instrument_id == instrument.id, ThresholdProfile.active.is_(True)
            )
            .order_by(desc(ThresholdProfile.created_at))
            .limit(1)
        )
        state = db.scalar(
            select(StrategyState).where(
                StrategyState.instrument_id == instrument.id,
                StrategyState.portfolio_kind == PortfolioKind.PAPER,
            )
        )
        thresholds = _threshold_dict(profile)
        if signal:
            candidates = thresholds["buys"] + thresholds["sells"]
            next_threshold = min(candidates, key=lambda value: abs(value - signal.score))
            signal_data = {
                "date": str(signal.date),
                "price": signal.price,
                "score": signal.score,
                "market_position": signal.market_position,
                "etf_position": signal.etf_position,
                "volatility": signal.volatility,
                "trend": signal.trend,
                "action": signal.action.value,
                "reason": signal.reason,
                "quality_status": signal.quality_status.value,
                "next_threshold": next_threshold,
                "distance_to_threshold": abs(signal.score - next_threshold),
            }
        else:
            signal_data = None
        payload.append(
            {
                "instrument": {
                    "id": instrument.id,
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "market": instrument.market.value,
                    "currency": instrument.currency,
                    "leverage": instrument.leverage,
                },
                "signal": signal_data,
                "thresholds": thresholds,
                "position_steps": state.position_steps if state else 0,
                "pending_delta": state.pending_delta if state else 0,
            }
        )
    return payload


@router.get("/signals/{symbol}/history", dependencies=[Depends(current_user)])
def signal_history(symbol: str, db: Session = Depends(get_db)) -> dict:
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if not instrument:
        raise HTTPException(404, "标的不存在")
    signals = list(
        db.scalars(
            select(SignalSnapshot)
            .where(SignalSnapshot.instrument_id == instrument.id)
            .order_by(SignalSnapshot.date)
        )
    )
    profile = db.scalar(
        select(ThresholdProfile)
        .where(ThresholdProfile.instrument_id == instrument.id, ThresholdProfile.active.is_(True))
        .order_by(desc(ThresholdProfile.created_at))
        .limit(1)
    )
    return {
        "instrument": {
            "id": instrument.id,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "currency": instrument.currency,
        },
        "thresholds": _threshold_dict(profile),
        "points": [
            {
                "date": str(item.date),
                "price": item.price,
                "score": item.score,
                "market_position": item.market_position,
                "etf_position": item.etf_position,
                "volatility": item.volatility,
                "trend": item.trend,
                "action": item.action.value,
                "reason": item.reason,
            }
            for item in signals
        ],
    }


@router.get("/backtests/{symbol}", dependencies=[Depends(current_user)])
def backtest(symbol: str, db: Session = Depends(get_db)) -> dict:
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if not instrument:
        raise HTTPException(404, "标的不存在")
    run = db.scalar(
        select(StrategyRun)
        .where(StrategyRun.instrument_id == instrument.id)
        .order_by(desc(StrategyRun.completed_at))
        .limit(1)
    )
    if not run:
        raise HTTPException(404, "尚未生成回测")
    return {
        "symbol": instrument.symbol,
        "start_date": str(run.start_date),
        "end_date": str(run.end_date),
        "friction_bps": run.friction_bps,
        "parameters": run.parameters,
        "metrics": run.metrics,
        "equity_curve": run.equity_curve,
        "completed_at": run.completed_at.isoformat(),
    }


@router.get("/trades", response_model=list[TradeOut], dependencies=[Depends(current_user)])
def list_trades(kind: PortfolioKind | None = None, db: Session = Depends(get_db)) -> list[Trade]:
    query = select(Trade).order_by(desc(Trade.executed_at), desc(Trade.id))
    if kind:
        query = query.where(Trade.portfolio_kind == kind)
    return list(db.scalars(query))


@router.post("/trades", response_model=TradeOut, dependencies=[Depends(current_user)])
def create_trade(payload: TradeCreate, db: Session = Depends(get_db)) -> Trade:
    instrument = db.get(Instrument, payload.instrument_id)
    if not instrument:
        raise HTTPException(404, "标的不存在")
    if payload.currency.upper() != instrument.currency:
        raise HTTPException(422, "成交币种须与品种币种一致")
    if payload.side == TradeSide.SELL:
        available = open_quantity(db, payload.instrument_id, payload.portfolio_kind)
        if payload.quantity > available:
            raise HTTPException(422, f"卖出数量超过可用持仓 {available}")
    values = payload.model_dump()
    values["currency"] = payload.currency.upper()
    trade = Trade(**values, source="manual")
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


@router.put("/trades/{trade_id}", response_model=TradeOut, dependencies=[Depends(current_user)])
def update_trade(trade_id: int, payload: TradeUpdate, db: Session = Depends(get_db)) -> Trade:
    trade = db.get(Trade, trade_id)
    if not trade or trade.source != "manual":
        raise HTTPException(404, "只能修改手工录入的成交")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(trade, key, value)
    db.commit()
    db.refresh(trade)
    return trade


@router.post("/trades/import", dependencies=[Depends(current_user)])
async def import_trades(file: UploadFile, db: Session = Depends(get_db)) -> dict:
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    instruments = {item.symbol: item for item in db.scalars(select(Instrument))}
    imported = 0
    errors: list[str] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            instrument = instruments[row["symbol"].upper()]
            portfolio_kind = PortfolioKind(row.get("portfolio_kind", "live"))
            side = TradeSide(row["side"].lower())
            quantity = Decimal(row["quantity"])
            if quantity <= 0:
                raise ValueError("quantity 必须大于 0")
            if side == TradeSide.SELL and quantity > open_quantity(
                db, instrument.id, portfolio_kind
            ):
                raise ValueError("卖出数量超过当前持仓")
            db.add(
                Trade(
                    instrument_id=instrument.id,
                    portfolio_kind=portfolio_kind,
                    side=side,
                    quantity=quantity,
                    price=Decimal(row["price"]),
                    fee=Decimal(row.get("fee") or "0"),
                    currency=row.get("currency") or instrument.currency,
                    executed_at=datetime.fromisoformat(row["executed_at"]),
                    note=row.get("note", ""),
                    source="csv",
                )
            )
            imported += 1
        except Exception as exc:
            errors.append(f"第 {line_number} 行：{exc}")
    if errors:
        db.rollback()
        raise HTTPException(422, {"message": "CSV 校验失败，未导入任何记录", "errors": errors})
    db.commit()
    return {"imported": imported}


@router.get("/portfolio", dependencies=[Depends(current_user)])
def portfolio(kind: PortfolioKind | None = None, db: Session = Depends(get_db)) -> dict:
    return portfolio_snapshot(db, kind)


@router.post("/jobs/recompute", status_code=202, dependencies=[Depends(current_user)])
def recompute(background: BackgroundTasks) -> dict:
    background.add_task(run_all_markets)
    return {"status": "accepted", "message": "已开始后台更新，完成后刷新看板"}


@router.get("/sentiment/{symbol}", dependencies=[Depends(current_user)])
def sentiment_observation(symbol: str, db: Session = Depends(get_db)) -> dict:
    from app.services.sentiment_observation import observation

    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
    if not instrument:
        raise HTTPException(404, "标的不存在")
    return observation(db, instrument)
