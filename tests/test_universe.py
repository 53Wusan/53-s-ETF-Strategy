from __future__ import annotations

import pandas as pd

from money_back.models import UniverseRules
from money_back.universe import build_point_in_time_universe, evaluate_data_gate


def _master() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "A",
                "name": "A ETF",
                "asset_type": "equity_etf",
                "listing_date": "2026-01-01",
                "delisting_date": "",
                "tracked_index_id": "IDX",
                "cross_border": False,
                "leveraged_inverse": False,
                "source": "fixture",
            },
            {
                "symbol": "B",
                "name": "B ETF",
                "asset_type": "equity_etf",
                "listing_date": "2026-01-01",
                "delisting_date": "2026-01-08",
                "tracked_index_id": "IDX",
                "cross_border": False,
                "leveraged_inverse": False,
                "source": "fixture",
            },
        ]
    )


def test_universe_is_point_in_time_and_deduplicates_by_liquidity() -> None:
    dates = pd.bdate_range("2026-01-01", periods=25)
    close = pd.DataFrame(1.0, index=dates, columns=["A", "B"])
    amount = pd.DataFrame({"A": 200_000_000.0, "B": 150_000_000.0}, index=dates)
    rules = UniverseRules(minimum_listing_days=2, minimum_median_amount_20d=100_000_000.0)
    mask, issues = build_point_in_time_universe(_master(), dates, close, amount, rules)
    assert not issues
    assert not mask.iloc[18].any()
    assert bool(mask.iloc[20]["A"])
    assert not bool(mask.iloc[20]["B"])


def test_data_gate_blocks_missing_delisted_turnover_and_second_source() -> None:
    result = evaluate_data_gate(
        master=_master(),
        includes_delisted=False,
        turnover_amount=None,
        dual_source_symbols=set(),
        expected_symbols={"A", "B"},
        required_start="2026-01-01",
    )
    assert result.status == "FAIL"
    assert not result.strict_dynamic_universe
    codes = {issue["code"] for issue in result.issues}
    assert {"survivorship_coverage_missing", "turnover_amount_missing", "dual_source_coverage_incomplete"} <= codes

