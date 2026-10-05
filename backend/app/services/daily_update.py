"""Deterministic daily desk update; never optimize rules or write actual trades."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.services.execution_data_refresh import refresh
from app.services.execution_research import dashboard
from app.services.research_cockpit import _research_output
from app.services.strategy_desk import observation_summary


def _save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def run(*, sync_quotes: bool = False) -> dict:
    root = _research_output() / "forward_data"
    root.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    previous_path = root / "daily_update.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
    try:
        manifest = refresh()
        plans = {}
        for profile in ("rank2", "short"):
            view = dashboard(profile)
            if view["stale"] or not view["next_open_plan"]:
                raise ValueError("行情或执行方案未就绪，不发布每日计划")
            plans[profile] = view["next_open_plan"]
        observations = {}
        for item in view["items"]:
            result = observation_summary(item["symbol"])
            observations[item["symbol"]] = result
        quotes = 0
        if sync_quotes:
            from app.db import SessionLocal
            from app.services.live_quote_refresh import sync_local_quotes
            with SessionLocal() as db:
                quotes = sync_local_quotes(db)
        result = {"status": "ok", "started_at": started,
                  "completed_at": datetime.now(timezone.utc).isoformat(),
                  "data_date": manifest["latest_completed_session"], "plans": plans,
                  "observations": observations, "quotes_added": quotes}
        _save(root / "daily_plan.json", result)
        _save(previous_path, {k: result[k] for k in ("status", "started_at", "completed_at", "data_date")})
        return result
    except Exception as exc:
        _save(previous_path, {"status": "failed", "started_at": started,
                             "completed_at": datetime.now(timezone.utc).isoformat(),
                             "last_successful_date": previous.get("data_date", previous.get("last_successful_date")),
                             "message": str(exc)})
        raise
