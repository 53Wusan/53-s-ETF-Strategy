from datetime import date

import pandas as pd
import pytest

from app.services import execution_data_refresh as refresh
from app.services.market_data import MarketDataError


def test_stale_public_history_uses_complete_yahoo_day(monkeypatch):
    public = pd.DataFrame(index=[date(2026, 10, 5)])
    yahoo = pd.DataFrame(index=[date(2026, 10, 5), date(2026, 10, 6)])
    monkeypatch.setattr(refresh.PublicHistoryProvider, "history", lambda *_: public)
    monkeypatch.setattr(refresh.YahooChartProvider, "history", lambda *_: yahoo)

    result = refresh._history_through("TQQQ", date(2026, 10, 6))

    assert result.index[-1] == pd.Timestamp("2026-10-06")
    assert result.attrs["provider"] == "yahoo"


def test_complete_public_history_does_not_call_fallback(monkeypatch):
    public = pd.DataFrame(index=[date(2026, 10, 6)])
    monkeypatch.setattr(refresh.PublicHistoryProvider, "history", lambda *_: public)
    monkeypatch.setattr(
        refresh.YahooChartProvider,
        "history",
        lambda *_: pytest.fail("complete primary source must not use fallback"),
    )

    assert refresh._history_through("TQQQ", date(2026, 10, 6)).index[-1] == pd.Timestamp("2026-10-06")


def test_two_stale_sources_do_not_publish_a_snapshot(monkeypatch):
    stale = pd.DataFrame(index=[date(2026, 10, 5)])
    monkeypatch.setattr(refresh.PublicHistoryProvider, "history", lambda *_: stale)
    monkeypatch.setattr(refresh.YahooChartProvider, "history", lambda *_: stale)

    with pytest.raises(MarketDataError, match="两个行情源均缺少"):
        refresh._history_through("TQQQ", date(2026, 10, 6))
