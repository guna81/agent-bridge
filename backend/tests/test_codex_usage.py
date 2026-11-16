import json
import sqlite3

from app import codex_usage
from app.rate_limits_reader import get_codex_rate_limits

RESULT = {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 100, "windowDurationMins": 10080, "resetsAt": 4102444800},
                         "secondary": None},
          "rateLimitsByLimitId": {"codex": {"limitId": "codex", "primary": {"usedPercent": 100, "windowDurationMins": 10080, "resetsAt": 4102444800},
                                            "secondary": None}}}


def test_parse_maps_windows_by_duration():
    parsed = codex_usage._parse({"rateLimits": {"primary": {"usedPercent": 40, "windowDurationMins": 300, "resetsAt": 1},
                                                "secondary": {"usedPercent": 7.5, "windowDurationMins": 10080, "resetsAt": 2}}})
    assert parsed["five_hour"]["used_percent"] == 40
    assert parsed["weekly"]["used_percent"] == 7.5
    assert codex_usage._parse({"rateLimits": {"primary": {"usedPercent": 1, "windowDurationMins": 60}}}) is None
    assert codex_usage._parse({}) is None


def test_live_numbers_override_stale_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    now = 1794756000
    monkeypatch.setattr("app.rate_limits_reader.time.time", lambda: now)
    monkeypatch.setattr(codex_usage, "live_snapshot", lambda: {
        **codex_usage._parse(RESULT), "fetched_at": now - 10, "refreshing": False, "refresh_error": None})
    limits = get_codex_rate_limits()
    assert limits["weekly"]["used_percent"] == 100
    assert limits["weekly"]["is_exhausted"]
    assert limits["five_hour"] is None
    assert not limits["is_stale"]


def test_logged_fallback_is_marked_stale_with_refresh_error(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    sessions = tmp_path / ".codex" / "sessions" / "2026" / "11" / "14"
    sessions.mkdir(parents=True)
    event = {"timestamp": "2026-11-14T17:08:44Z", "payload": {"type": "token_count", "rate_limits": {
        "limit_id": "codex", "primary": {"used_percent": 97, "window_minutes": 10080, "resets_at": 4102444800}}}}
    (sessions / "s.jsonl").write_text(json.dumps(event) + "\n")
    monkeypatch.setattr(codex_usage, "live_snapshot", lambda: {"refreshing": False, "refresh_error": "boom"})
    limits = get_codex_rate_limits()
    assert limits["weekly"]["used_percent"] == 97
    assert limits["is_stale"]
    assert limits["refresh_error"] == "boom"


def test_sqlite_fallback_uses_window_length_not_slot(tmp_path):
    db = tmp_path / "logs.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("create table logs (id integer primary key, ts integer, feedback_log_body text)")
    body = '{"x-codex-primary-used-percent": "97", "x-codex-primary-window-minutes": "10080", "x-codex-primary-reset-at": "4102444800"}'
    conn.execute("insert into logs (ts, feedback_log_body) values (1, ?)", (body,))
    conn.commit()
    conn.close()
    limits = get_codex_rate_limits(str(db))
    assert limits["five_hour"] is None
    assert limits["weekly"]["used_percent"] == 97
    assert limits["is_stale"]


def test_refresh_failure_keeps_snapshot_and_hides_details(monkeypatch):
    monkeypatch.setattr(codex_usage, "_snapshot", {"weekly": {"used_percent": 5}, "fetched_at": 1})
    monkeypatch.setattr(codex_usage, "_binary", lambda: "/bin/codex")
    monkeypatch.setattr(codex_usage, "_request_rate_limits", lambda binary: (_ for _ in ()).throw(ValueError("secret-token")))
    codex_usage._refresh()
    assert codex_usage._snapshot["weekly"]["used_percent"] == 5
    assert "secret" not in codex_usage._error
    assert codex_usage._next_attempt > 0
