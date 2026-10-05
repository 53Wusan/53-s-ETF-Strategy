from decimal import Decimal

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import Instrument, Market, PortfolioKind, StrategyState, ThresholdProfile

INSTRUMENTS = [
    ("KORU", "KORU", "Direxion Daily MSCI South Korea Bull 3X", Market.US, "USD", 3.0, "EWY", "MSCI South Korea proxy", "NYSE"),
    ("NAIL", "NAIL", "Direxion Daily Homebuilders & Supplies Bull 3X", Market.US, "USD", 3.0, "XHB", "S&P Homebuilders proxy", "NYSE"),
    ("FAS", "FAS", "Direxion Daily Financial Bull 3X", Market.US, "USD", 3.0, "XLF", "Financial Select Sector proxy", "NYSE"),
    ("TQQQ", "TQQQ", "ProShares UltraPro QQQ", Market.US, "USD", 3.0, "QQQ", "Nasdaq-100 proxy", "NYSE"),
    ("07447", "7447.HK", "CSOP Samsung Electronics Daily (2x)", Market.HK, "HKD", 2.0, "005930.KS", "Samsung Electronics", "HKEX"),
    ("CURE", "CURE", "Direxion Daily Healthcare Bull 3X", Market.US, "USD", 3.0, "XLV", "Health Care Select Sector proxy", "NYSE"),
    ("YINN", "YINN", "Direxion Daily FTSE China Bull 3X", Market.US, "USD", 3.0, "FXI", "FTSE China 50 proxy", "NYSE"),
    ("DFEN", "DFEN", "Direxion Daily Aerospace & Defense Bull 3X", Market.US, "USD", 3.0, "ITA", "US Aerospace & Defense proxy", "NYSE"),
    ("FNGU", "FNGU", "MicroSectors FANG+ Index 3X Leveraged ETN", Market.US, "USD", 3.0, "^NYFANG", "NYSE FANG+ Index", "NYSE"),
    ("GDXU", "GDXU", "MicroSectors Gold Miners 3X Leveraged ETN", Market.US, "USD", 3.0, "GDX", "NYSE Arca Gold Miners proxy", "NYSE"),
    ("LABU", "LABU", "Direxion Daily S&P Biotech Bull 3X", Market.US, "USD", 3.0, "XBI", "S&P Biotechnology proxy", "NYSE"),
    ("SPMO", "SPMO", "Invesco S&P 500 Momentum ETF", Market.US, "USD", 1.0, "SPY", "S&P 500 proxy", "NYSE"),
    ("07234", "7234.HK", "Bosera SZSE ChiNext Daily (2x)", Market.HK, "HKD", 2.0, "399006.SZ", "ChiNext Index", "HKEX"),
    ("SOXL", "SOXL", "Direxion Daily Semiconductor Bull 3X", Market.US, "USD", 3.0, "SOXX", "NYSE Semiconductor proxy", "NYSE"),
    ("TECL", "TECL", "Direxion Daily Technology Bull 3X", Market.US, "USD", 3.0, "XLK", "Technology Select Sector proxy", "NYSE"),
    ("UPRO", "UPRO", "ProShares UltraPro S&P 500", Market.US, "USD", 3.0, "SPY", "S&P 500 proxy", "NYSE"),
    ("EDC", "EDC", "Direxion Daily MSCI Emerging Markets Bull 3X", Market.US, "USD", 3.0, "EEM", "MSCI Emerging Markets proxy", "NYSE"),
    ("UGL", "UGL", "ProShares Ultra Gold", Market.US, "USD", 2.0, "GLD", "Gold proxy", "NYSE"),
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for row in INSTRUMENTS:
            symbol = row[0]
            instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
            if instrument is None:
                instrument = Instrument(
                    symbol=symbol,
                    yahoo_symbol=row[1],
                    name=row[2],
                    market=row[3],
                    currency=row[4],
                    leverage=row[5],
                    underlying_symbol=row[6],
                    underlying_name=row[7],
                    calendar=row[8],
                    strategy_capital=Decimal("10000"),
                )
                db.add(instrument)
                db.flush()
            if not db.scalar(
                select(ThresholdProfile).where(
                    ThresholdProfile.instrument_id == instrument.id,
                    ThresholdProfile.active.is_(True),
                )
            ):
                db.add(ThresholdProfile(instrument_id=instrument.id))
            if not db.scalar(
                select(StrategyState).where(
                    StrategyState.instrument_id == instrument.id,
                    StrategyState.portfolio_kind == PortfolioKind.PAPER,
                )
            ):
                db.add(StrategyState(instrument_id=instrument.id, portfolio_kind=PortfolioKind.PAPER))
        db.commit()
        from app.services.live_quote_refresh import sync_local_quotes
        sync_local_quotes(db)


if __name__ == "__main__":
    seed()

