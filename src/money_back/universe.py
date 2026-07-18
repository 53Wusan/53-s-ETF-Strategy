from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .models import DataIssue, UniverseRules


REQUIRED_MASTER_COLUMNS = {
    "symbol",
    "name",
    "asset_type",
    "listing_date",
    "delisting_date",
    "tracked_index_id",
    "cross_border",
    "leveraged_inverse",
    "source",
}


@dataclass(frozen=True)
class DataGateResult:
    status: str
    strict_dynamic_universe: bool
    earliest_complete_date: str | None
    includes_delisted: bool
    has_turnover_amount: bool
    has_dual_price_sources: bool
    issues: tuple[dict, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def validate_security_master(
    master: pd.DataFrame,
    *,
    includes_delisted: bool,
    required_start: str = "2016-01-01",
) -> list[DataIssue]:
    issues: list[DataIssue] = []
    missing = sorted(REQUIRED_MASTER_COLUMNS - set(master.columns))
    if missing:
        issues.append(
            DataIssue("master_missing_columns", "critical", f"Missing master columns: {missing}")
        )
        return issues
    duplicate = master[master["symbol"].duplicated(keep=False)]
    if not duplicate.empty:
        issues.append(
            DataIssue(
                "master_duplicate_symbols",
                "critical",
                "Security master contains duplicate symbols",
                evidence={"symbols": sorted(duplicate["symbol"].astype(str).unique().tolist())},
            )
        )
    listing = pd.to_datetime(master["listing_date"], errors="coerce")
    delisting = pd.to_datetime(master["delisting_date"], errors="coerce")
    if listing.isna().any():
        issues.append(
            DataIssue(
                "missing_listing_dates",
                "critical",
                "Every instrument requires a listing date",
                evidence={"count": int(listing.isna().sum())},
            )
        )
    invalid_order = delisting.notna() & listing.notna() & (delisting < listing)
    if invalid_order.any():
        issues.append(
            DataIssue(
                "invalid_listing_interval",
                "critical",
                "Delisting date precedes listing date",
                evidence={"count": int(invalid_order.sum())},
            )
        )
    if not includes_delisted:
        issues.append(
            DataIssue(
                "survivorship_coverage_missing",
                "critical",
                "Free master does not prove coverage of delisted ETFs",
            )
        )
    if listing.notna().any() and listing.min() > pd.Timestamp(required_start):
        issues.append(
            DataIssue(
                "history_starts_too_late",
                "critical",
                f"Master coverage begins after {required_start}",
                evidence={"first_listing": listing.min().date().isoformat()},
            )
        )
    return issues


def build_point_in_time_universe(
    master: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    adjusted_close: pd.DataFrame,
    turnover_amount: pd.DataFrame | None,
    rules: UniverseRules,
) -> tuple[pd.DataFrame, list[DataIssue]]:
    """Return an as-of eligibility mask without using future listings or liquidity."""
    issues: list[DataIssue] = []
    mask = pd.DataFrame(False, index=calendar, columns=adjusted_close.columns)
    amount_median = (
        turnover_amount.reindex(calendar).rolling(20, min_periods=20).median()
        if turnover_amount is not None
        else None
    )
    if amount_median is None:
        issues.append(
            DataIssue(
                "turnover_amount_missing",
                "critical",
                "20-day median turnover amount is required for the liquidity gate",
            )
        )

    records = master.set_index(master["symbol"].astype(str), drop=False)
    for symbol in adjusted_close.columns.astype(str):
        if symbol not in records.index:
            issues.append(
                DataIssue("symbol_missing_from_master", "critical", "Symbol absent from master", symbol)
            )
            continue
        row = records.loc[symbol]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        if str(row["asset_type"]) not in rules.asset_types:
            continue
        if rules.exclude_cross_border and bool(row["cross_border"]):
            continue
        if rules.exclude_leveraged_inverse and bool(row["leveraged_inverse"]):
            continue
        listing_date = pd.Timestamp(row["listing_date"])
        delisting_value = row["delisting_date"]
        delisting_date = (
            pd.Timestamp(delisting_value)
            if pd.notna(delisting_value) and str(delisting_value).strip()
            else pd.Timestamp.max
        )
        price_exists = adjusted_close[symbol].notna()
        trading_age = price_exists.cumsum()
        eligible = (
            (calendar >= listing_date)
            & (calendar <= delisting_date)
            & price_exists
            & (trading_age >= rules.minimum_listing_days)
        )
        if amount_median is not None and symbol in amount_median:
            eligible &= amount_median[symbol] >= rules.minimum_median_amount_20d
        else:
            eligible &= False
        mask[symbol] = eligible

    if rules.deduplicate_tracked_index and amount_median is not None:
        for tracked_index, group in master.groupby("tracked_index_id", dropna=False):
            if pd.isna(tracked_index) or str(tracked_index).strip() == "":
                continue
            symbols = [str(value) for value in group["symbol"] if str(value) in mask.columns]
            if len(symbols) < 2:
                continue
            liquidity = amount_median[symbols].where(mask[symbols])
            any_valid = liquidity.notna().any(axis=1)
            winners = liquidity.fillna(-np.inf).idxmax(axis=1).where(any_valid)
            for symbol in symbols:
                mask[symbol] &= winners.eq(symbol)
    return mask, issues


def evaluate_data_gate(
    *,
    master: pd.DataFrame,
    includes_delisted: bool,
    turnover_amount: pd.DataFrame | None,
    dual_source_symbols: set[str],
    expected_symbols: set[str],
    required_start: str = "2016-01-01",
    additional_issues: list[DataIssue] | None = None,
) -> DataGateResult:
    issues = validate_security_master(
        master, includes_delisted=includes_delisted, required_start=required_start
    )
    issues.extend(additional_issues or [])
    has_turnover = turnover_amount is not None
    if not has_turnover:
        issues.append(
            DataIssue("turnover_amount_missing", "critical", "No auditable turnover amount matrix")
        )
    has_dual = expected_symbols.issubset(dual_source_symbols)
    if not has_dual:
        issues.append(
            DataIssue(
                "dual_source_coverage_incomplete",
                "critical",
                "Not every ETF has a second independently sourced price series",
                evidence={"missing": sorted(expected_symbols - dual_source_symbols)},
            )
        )
    listing = pd.to_datetime(master.get("listing_date"), errors="coerce")
    earliest = listing.min().date().isoformat() if listing.notna().any() else None
    critical = any(issue.severity == "critical" for issue in issues)
    return DataGateResult(
        status="FAIL" if critical else "PASS",
        strict_dynamic_universe=not critical,
        earliest_complete_date=earliest,
        includes_delisted=includes_delisted,
        has_turnover_amount=has_turnover,
        has_dual_price_sources=has_dual,
        issues=tuple(asdict(issue) for issue in issues),
    )
