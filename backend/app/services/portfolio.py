from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DailyBar, FxRate, Instrument, PortfolioKind, Trade, TradeSide


def _apply_splits(db: Session, instrument_id: int, quantity: Decimal, start: date | None, end: date) -> Decimal:
    conditions = [
        DailyBar.instrument_id == instrument_id,
        DailyBar.date <= end,
        DailyBar.split_factor != 1,
    ]
    if start is not None:
        conditions.append(DailyBar.date > start)
    # The same action may be present in multiple sources; one factor per date is enough.
    factors_by_date = {}
    for event_date, factor in db.execute(
        select(DailyBar.date, DailyBar.split_factor).where(*conditions)
    ):
        factors_by_date[event_date] = Decimal(str(factor))
    for factor in factors_by_date.values():
        quantity *= factor
    return quantity


def latest_fx_rate(db: Session, base: str, quote: str) -> float | None:
    if base == quote:
        return 1.0
    direct = db.scalar(
        select(FxRate)
        .where(FxRate.base == base, FxRate.quote == quote)
        .order_by(desc(FxRate.date))
        .limit(1)
    )
    if direct:
        return direct.rate
    inverse = db.scalar(
        select(FxRate)
        .where(FxRate.base == quote, FxRate.quote == base)
        .order_by(desc(FxRate.date))
        .limit(1)
    )
    return 1 / inverse.rate if inverse and inverse.rate else None


def portfolio_snapshot(db: Session, kind: PortfolioKind | None = None) -> dict:
    settings = get_settings()
    query = select(Trade).order_by(Trade.executed_at, Trade.id)
    if kind:
        query = query.where(Trade.portfolio_kind == kind)
    trades = list(db.scalars(query))
    instruments = {instrument.id: instrument for instrument in db.scalars(select(Instrument))}
    books: dict[tuple[PortfolioKind, int], dict] = defaultdict(
        lambda: {"quantity": Decimal("0"), "cost": Decimal("0"), "realized": Decimal("0"), "fees": Decimal("0"), "split_date": None}
    )
    for trade in trades:
        book = books[(trade.portfolio_kind, trade.instrument_id)]
        trade_date = trade.executed_at.date()
        book["quantity"] = _apply_splits(
            db, trade.instrument_id, book["quantity"], book["split_date"], trade_date
        )
        book["split_date"] = trade_date
        quantity = Decimal(trade.quantity)
        value = quantity * Decimal(trade.price)
        book["fees"] += Decimal(trade.fee)
        if trade.side == TradeSide.BUY:
            book["quantity"] += quantity
            book["cost"] += value + Decimal(trade.fee)
        elif book["quantity"] > 0:
            sell_quantity = min(quantity, book["quantity"])
            allocated_cost = book["cost"] * sell_quantity / book["quantity"]
            book["realized"] += value - Decimal(trade.fee) - allocated_cost
            book["quantity"] -= sell_quantity
            book["cost"] -= allocated_cost

    positions: list[dict] = []
    totals = {"market_value": 0.0, "cost": 0.0, "realized": 0.0, "unrealized": 0.0, "fees": 0.0}
    missing_fx: set[str] = set()
    for (portfolio_kind, instrument_id), book in books.items():
        instrument = instruments[instrument_id]
        latest_bar = db.scalar(
            select(DailyBar)
            .where(DailyBar.instrument_id == instrument_id)
            .order_by(desc(DailyBar.date))
            .limit(1)
        )
        if latest_bar:
            book["quantity"] = _apply_splits(
                db, instrument_id, book["quantity"], book["split_date"], latest_bar.date
            )
        last_price = Decimal(str(latest_bar.close)) if latest_bar else Decimal("0")
        market_value = book["quantity"] * last_price
        unrealized = market_value - book["cost"]
        rate = latest_fx_rate(db, instrument.currency, settings.base_currency)
        if rate is None:
            missing_fx.add(instrument.currency)
        else:
            totals["market_value"] += float(market_value) * rate
            totals["cost"] += float(book["cost"]) * rate
            totals["realized"] += float(book["realized"]) * rate
            totals["unrealized"] += float(unrealized) * rate
            totals["fees"] += float(book["fees"]) * rate
        positions.append(
            {
                "portfolio_kind": portfolio_kind.value,
                "instrument_id": instrument_id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "currency": instrument.currency,
                "quantity": float(book["quantity"]),
                "average_cost": float(book["cost"] / book["quantity"]) if book["quantity"] else 0,
                "last_price": float(last_price),
                "market_value": float(market_value),
                "realized_pnl": float(book["realized"]),
                "unrealized_pnl": float(unrealized),
                "fees": float(book["fees"]),
                "latest_price_date": str(latest_bar.date) if latest_bar else None,
            }
        )
    return {
        "base_currency": settings.base_currency,
        "totals": totals,
        "positions": positions,
        "missing_fx": sorted(missing_fx),
    }


def open_quantity(db: Session, instrument_id: int, kind: PortfolioKind) -> Decimal:
    snapshot = portfolio_snapshot(db, kind)
    for position in snapshot["positions"]:
        if position["instrument_id"] == instrument_id:
            return Decimal(str(position["quantity"]))
    return Decimal("0")
