import json
from types import SimpleNamespace

from app import rate_limits_reader as reader


def test_cli_usage_populates_quota_cache(tmp_path, monkeypatch):
    payload = {"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "buckets": [
            {"window": "weekly", "remaining_fraction": 0.4775, "reset_time": "2026-11-14T06:31:26Z"},
            {"window": "5h", "remaining_fraction": 0.8588, "reset_time": "2026-11-12T18:53:47Z"},
        ]},
        {"name": "Claude and GPT models", "buckets": [
            {"window": "5h", "remaining_fraction": 1.0},
        ]},
    ]}}}
    monkeypatch.setattr(reader.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps(payload)))
    monkeypatch.setattr(reader, "_agy_refresh_lock", __import__("threading").Lock())
    monkeypatch.setattr(reader, "_schedule_agy_refresh", lambda path: None)
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr("app.status_bar_config.load_status_bar_config", lambda: SimpleNamespace(antigravity_ls_address="", antigravity_csrf_token=""))
    reader._agy_refresh_lock.acquire()
    reader._refresh_agy_usage(tmp_path / "antigravity_quota_cache.json")
    limits = reader.get_antigravity_rate_limits()
    assert limits["weekly"]["left_percent"] == 48
    assert limits["five_hour"]["left_percent"] == 86
    assert limits["claude_gpt_5h"]["left_percent"] == 100
    assert limits["five_hour"]["reset_at"] is not None
    assert limits["updated_at"] is not None


def test_failed_cli_refresh_preserves_previous_cache(tmp_path, monkeypatch):
    cache = tmp_path / "antigravity_quota_cache.json"
    cache.write_text("previous")
    monkeypatch.setattr(reader.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout='{"status":"ERROR"}'))
    monkeypatch.setattr(reader, "_agy_refresh_lock", __import__("threading").Lock())
    reader._agy_refresh_lock.acquire()
    reader._refresh_agy_usage(cache)
    assert cache.read_text() == "previous"
