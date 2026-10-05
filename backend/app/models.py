from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Market(str, enum.Enum):
    US = "US"
    HK = "HK"


class PortfolioKind(str, enum.Enum):
    PAPER = "paper"
    LIVE = "live"


class TradeSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class SignalAction(str, enum.Enum):
    HOLD = "hold"
    BUY = "buy"
    ADD = "add"
    REDUCE = "reduce"
    EXIT = "exit"
    DATA_BLOCKED = "data_blocked"


class QualityStatus(str, enum.Enum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    yahoo_symbol: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(160))
    market: Mapped[Market] = mapped_column(Enum(Market, native_enum=False))
    currency: Mapped[str] = mapped_column(String(3))
    leverage: Mapped[float] = mapped_column(Float)
    underlying_symbol: Mapped[str] = mapped_column(String(30))
    underlying_name: Mapped[str] = mapped_column(String(160))
    calendar: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    strategy_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("10000"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bars: Mapped[list[DailyBar]] = relationship(back_populates="instrument")


class DailyBar(Base):
    __tablename__ = "daily_bars"
    __table_args__ = (
        UniqueConstraint("instrument_id", "date", "source", name="uq_bar_source_date"),
        Index("ix_bar_instrument_date", "instrument_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adjusted_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    split_factor: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(40), default="yahoo")
    quality_status: Mapped[QualityStatus] = mapped_column(
        Enum(QualityStatus, native_enum=False), default=QualityStatus.OK
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    instrument: Mapped[Instrument] = relationship(back_populates="bars")


class ReferenceSignal(Base):
    __tablename__ = "reference_signals"
    __table_args__ = (UniqueConstraint("instrument_id", "date", name="uq_reference_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    extraction_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    manually_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source_file: Mapped[str] = mapped_column(String(255))


class ThresholdProfile(Base):
    __tablename__ = "threshold_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)
    buy_1: Mapped[float] = mapped_column(Float, default=-60)
    buy_2: Mapped[float] = mapped_column(Float, default=-75)
    buy_3: Mapped[float] = mapped_column(Float, default=-90)
    sell_1: Mapped[float] = mapped_column(Float, default=60)
    sell_2: Mapped[float] = mapped_column(Float, default=75)
    sell_3: Mapped[float] = mapped_column(Float, default=90)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    method: Mapped[str] = mapped_column(String(80), default="fallback")
    train_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    train_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    validation_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"
    __table_args__ = (UniqueConstraint("instrument_id", "date", name="uq_signal_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    market_position: Mapped[float] = mapped_column(Float)
    etf_position: Mapped[float] = mapped_column(Float)
    volatility: Mapped[float] = mapped_column(Float)
    trend: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    action: Mapped[SignalAction] = mapped_column(Enum(SignalAction, native_enum=False))
    target_step_delta: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    quality_status: Mapped[QualityStatus] = mapped_column(
        Enum(QualityStatus, native_enum=False), default=QualityStatus.OK
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    threshold_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("threshold_profiles.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(30), default="v1")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    friction_bps: Mapped[float] = mapped_column(Float)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    equity_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("ix_trade_portfolio_time", "portfolio_kind", "executed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), index=True)
    portfolio_kind: Mapped[PortfolioKind] = mapped_column(Enum(PortfolioKind, native_enum=False))
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide, native_enum=False))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    signal_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("signal_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyState(Base):
    __tablename__ = "strategy_states"
    __table_args__ = (UniqueConstraint("instrument_id", "portfolio_kind", name="uq_strategy_state"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    portfolio_kind: Mapped[PortfolioKind] = mapped_column(
        Enum(PortfolioKind, native_enum=False), default=PortfolioKind.PAPER
    )
    position_steps: Mapped[int] = mapped_column(Integer, default=0)
    buy_mask: Mapped[int] = mapped_column(Integer, default=0)
    sell_mask: Mapped[int] = mapped_column(Integer, default=0)
    cycle_id: Mapped[int] = mapped_column(Integer, default=0)
    pending_delta: Mapped[int] = mapped_column(Integer, default=0)
    pending_signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signal_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    pending_signal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("date", "base", "quote", name="uq_fx_rate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    rate: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="yahoo")


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(180), unique=True)
    channel: Mapped[str] = mapped_column(String(30), default="feishu")
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(80), index=True)
    market: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")

