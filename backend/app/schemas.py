from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import PortfolioKind, TradeSide


class LoginRequest(BaseModel):
    username: str
    password: str


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    market: str
    currency: str
    leverage: float
    underlying_symbol: str
    underlying_name: str
    enabled: bool
    strategy_capital: Decimal
    latest_bar_date: date | None = None
    data_status: str = "unknown"


class TradeCreate(BaseModel):
    instrument_id: int
    portfolio_kind: PortfolioKind = PortfolioKind.LIVE
    side: TradeSide
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(min_length=3, max_length=3)
    executed_at: datetime
    note: str = Field(default="", max_length=500)


class TradeUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    fee: Decimal | None = Field(default=None, ge=0)
    executed_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument_id: int
    portfolio_kind: PortfolioKind
    side: TradeSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    currency: str
    executed_at: datetime
    note: str
    source: str


class SignalPoint(BaseModel):
    date: date
    price: float
    market_position: float
    etf_position: float
    volatility: float
    trend: float
    score: float
    action: str
    quality_status: str

