"""Refresh subscription usage without modifying Claude Code's credential/cache files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import httpx

REFRESH_SECONDS = 120
_lock = threading.Lock()
_snapshot: dict = {}
_next_attempt = 0.0
_refreshing = False
_error: str | None = None


def _access_token() -> str:
    directory = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    try:
        credentials = json.loads((directory / ".credentials.json").read_text())
    except (OSError, ValueError):
        if sys.platform != "darwin" or os.environ.get("CLAUDE_CONFIG_DIR"):
            raise ValueError("Claude Code login unavailable") from None
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        credentials = json.loads(result.stdout)
    token = credentials.get("claudeAiOauth", {}).get("accessToken")
    if not isinstance(token, str) or not token:
        raise ValueError("Claude Code login unavailable")
    return token


def _refresh() -> None:
    global _snapshot, _next_attempt, _refreshing, _error
    delay = REFRESH_SECONDS
    try:
        token = _access_token()
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(
                "https://api.anthropic.com/api/oauth/usage",
                headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"},
            )
        response.raise_for_status()
        usage = response.json()
        if not isinstance(usage, dict) or not any(
            isinstance(usage.get(key), dict) and isinstance(usage[key].get("utilization"), (int, float))
            for key in ("five_hour", "seven_day")
        ):
            raise ValueError("Invalid usage response")
        with _lock:
            _snapshot = {"utilization": usage, "fetchedAtMs": time.time() * 1000}
            _error = None
    except Exception as exc:
        # Never expose exception text: HTTP errors can contain credential headers.
        message = "Unable to refresh Claude usage; showing last reported values."
        delay = 300
        if isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code == 429:
                message = "Claude usage refresh rate limited; retrying later."
                try:
                    delay = max(delay, min(3600, int(exc.response.headers.get("retry-after", "300"))))
                except ValueError:
                    pass
            elif exc.response.status_code in (401, 403):
                message = "Claude login needs renewal; open Claude Code and sign in."
        with _lock:
            _error = message
    finally:
        with _lock:
            _next_attempt = time.monotonic() + delay
            _refreshing = False


def usage_snapshot(path: str, *, refresh: bool = True) -> dict:
    """Return immediately; one background request per refresh period."""
    global _refreshing
    try:
        cached = json.loads(Path(path).read_text()).get("cachedUsageUtilization", {})
        if not isinstance(cached, dict):
            cached = {}
    except (OSError, ValueError, AttributeError):
        cached = {}
    if not refresh:
        return cached
    with _lock:
        if time.monotonic() >= _next_attempt and not _refreshing:
            _refreshing = True
            threading.Thread(target=_refresh, daemon=True).start()
        latest = max((cached, _snapshot), key=lambda item: item.get("fetchedAtMs") or 0)
        return {**latest, "refreshing": _refreshing, "refresh_error": _error}
