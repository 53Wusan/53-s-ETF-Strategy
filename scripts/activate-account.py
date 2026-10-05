"""Freeze the first executable session, never simulate an already-passed open."""
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

root = Path(__file__).resolve().parents[1]
path = root / "account/config.json"
config = json.loads(path.read_text(encoding="utf8"))
if not config.get("activation_date"):
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/New_York"))
    from datetime import timedelta
    schedule = mcal.get_calendar("NYSE").schedule(start_date=local.date(), end_date=local.date()+timedelta(days=14))
    next_session = next(day for day, row in schedule.iterrows() if row.market_open.to_pydatetime() > now)
    config.update(activation_date=str(next_session.date()), activated_at=now.isoformat(), status="paper_active")
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Paper account starts at the next eligible open: {config['activation_date']}")
else:
    print(f"Existing activation date retained: {config['activation_date']}")
