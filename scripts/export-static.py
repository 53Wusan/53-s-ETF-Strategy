"""Export market/research views only: no credentials, account config or real trades."""
import json
from pathlib import Path
import pandas as pd
import pandas_market_calendars as mcal

from app.services.execution_research import dashboard, history_view
from app.services.research_cockpit import DEFAULT_SYMBOLS
from app.services.strategy_desk import curated_strategies, observation_summary, strategy_detail

root = Path(__file__).resolve().parents[1] / "frontend/public/data"


def save(path, value):
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf8")


for profile in ("rank2", "short"):
    catalog = dashboard(profile)
    last = pd.Timestamp(catalog["cutoff"])
    schedule = mcal.get_calendar("NYSE").schedule(start_date=last+pd.Timedelta(days=1), end_date=last+pd.Timedelta(days=14))
    catalog["valid_until"] = (schedule.iloc[0].market_close+pd.Timedelta(minutes=30)).isoformat()
    save(f"catalog-{profile}.json", catalog)
for symbol in DEFAULT_SYMBOLS:
    save(f"history-{symbol}.json", history_view(symbol, 0))
    save(f"observation-{symbol}.json", observation_summary(symbol))
cards = curated_strategies()
save("strategies.json", cards)
for item in cards["items"]:
    save(f"strategy-{item['id']}.json", strategy_detail(item["id"]))
print("Static market/research views exported; private account omitted")
