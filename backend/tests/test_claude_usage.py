import json
from types import SimpleNamespace

import httpx
import pytest

from app import claude_usage as usage
from app.rate_limits_reader import get_claude_rate_limits


@pytest.fixture
def cache(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps({"cachedUsageUtilization": {
        "fetchedAtMs": 1000,
        "utilization": {"five_hour": {"utilization": 11}, "seven_day": {"utilization": 96}},
    }}))
    monkeypatch.setattr(usage, "_snapshot", {})
    monkeypatch.setattr(usage, "_next_attempt", 0)
    monkeypatch.setattr(usage, "_refreshing", False)
    monkeypatch.setattr(usage, "_error", None)
    monkeypatch.setattr(usage, "_access_token", lambda: "test-token")
    return path


def mock_response(monkeypatch, status=200, body=None, headers=None):
    response = httpx.Response(status, json=body or {}, headers=headers,
                              request=httpx.Request("GET", "https://api.anthropic.com/api/oauth/usage"))
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers):
            assert url == "https://api.anthropic.com/api/oauth/usage"
            assert headers["Authorization"] == "Bearer test-token"
            return response
    monkeypatch.setattr(usage.httpx, "Client", Client)


def test_live_usage_replaces_stale_cli_cache_without_modifying_it(cache, monkeypatch):
    original = cache.read_bytes()
    mock_response(monkeypatch, body={"five_hour": {"utilization": 24}, "seven_day": {"utilization": 99}})
    usage._refresh()
    snapshot = usage.usage_snapshot(str(cache))
    assert snapshot["utilization"]["five_hour"]["utilization"] == 24
    assert snapshot["utilization"]["seven_day"]["utilization"] == 99
    assert snapshot["fetchedAtMs"] > 1000
    assert snapshot["refresh_error"] is None
    assert cache.read_bytes() == original


def test_polling_starts_only_one_background_refresh(cache, monkeypatch):
    workers = []
    monkeypatch.setattr(usage.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: workers.append(kw)))
    for _ in range(10):
        snapshot = usage.usage_snapshot(str(cache))
        assert snapshot["utilization"]["seven_day"]["utilization"] == 96
        assert snapshot["refreshing"]
    assert len(workers) == 1


@pytest.mark.parametrize("status", [401, 429, 500])
def test_refresh_failure_retains_usage_and_backs_off(cache, monkeypatch, status):
    mock_response(monkeypatch, body={"five_hour": {"utilization": 24}})
    usage._refresh()
    previous = usage._snapshot.copy()
    mock_response(monkeypatch, status=status, headers={"retry-after": "900"})
    before = usage.time.monotonic()
    usage._refresh()
    snapshot = usage.usage_snapshot(str(cache))
    assert usage._snapshot == previous
    assert snapshot["refresh_error"]
    assert "test-token" not in snapshot["refresh_error"]
    assert not snapshot["refreshing"]
    assert usage._next_attempt >= before + (900 if status == 429 else 300)


def test_custom_cache_does_not_start_live_refresh(cache, monkeypatch):
    monkeypatch.setattr(usage.threading, "Thread", lambda **kw: pytest.fail("Custom file must remain isolated"))
    limits = get_claude_rate_limits(str(cache))
    assert limits["weekly"]["used_percent"] == 96
    assert limits["updated_at"] == 1
    assert limits["is_stale"]


def test_inactive_session_does_not_hide_weekly_usage(cache):
    cache.write_text(json.dumps({"cachedUsageUtilization": {
        "utilization": {"five_hour": None, "seven_day": {"utilization": 99}, "limits": None},
    }}))
    limits = get_claude_rate_limits(str(cache))
    assert limits["five_hour"] is None
    assert limits["weekly"]["left_percent"] == 1


def test_newer_cli_cache_wins(cache, monkeypatch):
    monkeypatch.setattr(usage, "_snapshot", {"fetchedAtMs": 500, "utilization": {"seven_day": {"utilization": 1}}})
    monkeypatch.setattr(usage, "_next_attempt", float("inf"))
    assert usage.usage_snapshot(str(cache))["utilization"]["seven_day"]["utilization"] == 96


def test_refresh_resumes_after_interval(cache, monkeypatch):
    mock_response(monkeypatch, body={"five_hour": {"utilization": 24}})
    usage._refresh()
    deadline = usage._next_attempt
    workers = []
    monkeypatch.setattr(usage.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: workers.append(kw)))
    monkeypatch.setattr(usage.time, "monotonic", lambda: deadline - 1)
    usage.usage_snapshot(str(cache))
    assert not workers
    monkeypatch.setattr(usage.time, "monotonic", lambda: deadline + 1)
    usage.usage_snapshot(str(cache))
    assert len(workers) == 1


def test_credentials_file_token_is_read_without_rewriting(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    credentials = tmp_path / ".credentials.json"
    credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "existing-login"}}))
    original = credentials.read_bytes()
    assert usage._access_token() == "existing-login"
    assert credentials.read_bytes() == original
