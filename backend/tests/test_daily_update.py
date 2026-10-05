import json

import pytest

from app.services import daily_update as daily


def fake_view(profile):
    return {"stale": False, "items": [{"symbol": "TQQQ"}],
            "next_open_plan": {"signal_date": "2026-10-02", "actions": [], "profile": profile}}


def test_daily_update_is_repeatable_and_never_calls_a_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "_research_output", lambda: tmp_path)
    monkeypatch.setattr(daily, "refresh", lambda: {"latest_completed_session": "2026-10-02"})
    monkeypatch.setattr(daily, "dashboard", fake_view)
    monkeypatch.setattr(daily, "observation_summary", lambda symbol: {"symbol": symbol})
    first = daily.run()
    second = daily.run()
    assert first["plans"] == second["plans"]
    assert second["quotes_added"] == 0
    receipt = json.loads((tmp_path / "forward_data/daily_plan.json").read_text())
    assert set(receipt["plans"]) == {"rank2", "short"}


def test_failed_update_preserves_the_last_successful_plan(tmp_path, monkeypatch):
    root = tmp_path / "forward_data"
    root.mkdir()
    old = '{"data_date":"2026-10-01","plans":{"saved":true}}'
    (root / "daily_plan.json").write_text(old)
    (root / "daily_update.json").write_text('{"status":"ok","data_date":"2026-10-01"}')
    monkeypatch.setattr(daily, "_research_output", lambda: tmp_path)
    monkeypatch.setattr(daily, "refresh", lambda: {"latest_completed_session": "2026-10-02"})
    monkeypatch.setattr(daily, "dashboard", lambda profile: {"stale": True})
    with pytest.raises(ValueError, match="行情或执行方案"):
        daily.run()
    assert (root / "daily_plan.json").read_text() == old
    receipt = json.loads((root / "daily_update.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["last_successful_date"] == "2026-10-01"
