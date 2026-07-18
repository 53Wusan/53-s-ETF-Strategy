from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from money_back.data import CORE_GATE_INDICES, ETF_SYMBOLS, load_market_data


def main() -> None:
    bundle = load_market_data(
        "2023-01-01", "2026-07-08", cache_dir=ROOT / "data" / "cache", include_raw=False
    )
    calendar = bundle.adjusted["上证指数"].index
    fixture = pd.DataFrame(index=calendar)
    for symbol in ETF_SYMBOLS:
        for field in ["open", "close", "high", "low", "volume"]:
            fixture[f"etf_{symbol}_{field}"] = bundle.adjusted[symbol][field].reindex(calendar)
    for label in CORE_GATE_INDICES:
        fixture[f"index_{label}_close"] = bundle.adjusted[label]["close"].reindex(calendar)
    destination = ROOT / "tests" / "fixtures" / "t5_v0_1_prices.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fixture.rename_axis("date").reset_index().to_csv(
        destination, index=False, encoding="utf-8"
    )
    print(destination)


if __name__ == "__main__":
    main()

