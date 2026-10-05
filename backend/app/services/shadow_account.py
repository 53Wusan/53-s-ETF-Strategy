"""Deployment-date paper account, isolated from historical and actual ledgers."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from app.services.execution_research import CapitalPolicy, ExecutionRule, FX, load_arrays, simulate


def calculate(config: dict, data: dict) -> dict:
    start = pd.Timestamp(config["activation_date"])
    capital = CapitalPolicy(initial_usd=float(config["initial_usd"]), reserve_hkd=0)
    rule = ExecutionRule(**config["rule"])
    last = data["dates"][-1]
    if last < start:
        current = {"cash_usd": capital.initial_usd, "equity_usd": capital.initial_usd,
                   "positions": {}, "trades": []}
    else:
        completed = simulate(data, rule, start=str(start.date()), detail=True, capital=capital)
        day = completed["daily"][-1]
        current = {"cash_usd": day["cash_hkd"] / FX, "equity_usd": day["equity_hkd"] / FX,
                   "positions": day["positions"], "trades": completed["trades"]}
    sessions = mcal.get_calendar("NYSE").valid_days(start_date=last+pd.Timedelta(days=1),
                                                   end_date=max(last, start)+pd.Timedelta(days=14))
    upcoming = pd.Timestamp(sessions[0].date())
    if upcoming < start:
        return {"kind": "paper_account", "currency": "USD", "profile": "rank2",
                "activation_date": str(start.date()), "data_date": str(last.date()),
                "initial_usd": capital.initial_usd, "buy_budget_usd": capital.initial_usd * .05,
                **current, "next_open_plan": {"signal_date": None, "next_open_date": str(start.date()),
                                              "actions": [], "status": "waiting_for_activation_signal"}}
    projected = {"dates": data["dates"].append(pd.DatetimeIndex([upcoming])), "symbols": data["symbols"]}
    for key in ("open", "close", "score"):
        projected[key] = np.vstack([data[key], data["score"][-1] if key == "score" else data["close"][-1]])
    replay = simulate(projected, rule, start=str(start.date()), detail=True, capital=capital)
    actions = [t for t in replay["trades"] if t["date"] == str(upcoming.date())]
    return {"kind": "paper_account", "currency": "USD", "profile": "rank2",
            "activation_date": str(start.date()), "data_date": str(last.date()),
            "fee_status": "provisional_0.1pct_each_side", "share_basis": "fractional_adjusted_research_units",
            "initial_usd": capital.initial_usd, "buy_budget_usd": capital.initial_usd * .05,
            **current, "next_open_plan": {"signal_date": str(last.date()),
                                           "next_open_date": str(upcoming.date()), "actions": actions}}


def update(config_path: Path, output_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf8"))
    result = calculate(config, load_arrays())
    if output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf8"))
        historical = [t for t in result["trades"] if t["date"] <= previous["data_date"]]
        if previous["activation_date"] != result["activation_date"] or historical != previous["trades"]:
            raise ValueError("已登记模拟成交发生变化，必须先对账，不覆盖旧账本")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    os.replace(temporary, output_path)
    return result
