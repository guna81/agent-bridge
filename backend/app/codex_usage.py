"""Live Codex subscription limits via the CLI's own app-server (`account/rateLimits/read`).

Codex only writes limits to its logs after a request, so those can be hours old. Asking the
app-server returns the account's current numbers. Runs in the background and never blocks.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time

REFRESH_SECONDS = 120
ERROR_SECONDS = 300
_ENV_KEYS = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "APPDATA",
             "LOCALAPPDATA", "USERPROFILE", "CODEX_HOME")
_lock = threading.Lock()
_snapshot: dict = {}
_next_attempt = 0.0
_refreshing = False
_error: str | None = None


def _binary() -> str | None:
    found = shutil.which("codex")
    if found:
        return found
    for candidate in ("~/.local/bin/codex", "/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
        path = os.path.expanduser(candidate)
        if os.access(path, os.X_OK):
            return path
    return None


def _request_rate_limits(binary: str) -> dict:
    env = {name: os.environ[name] for name in _ENV_KEYS if name in os.environ}
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.Popen([binary, "app-server", "--stdio"], cwd=cwd, env=env, text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        watchdog = threading.Timer(20, proc.kill)
        watchdog.start()
        try:
            def send(message: dict) -> None:
                proc.stdin.write(json.dumps(message) + "\n")
                proc.stdin.flush()

            def receive(request_id: int) -> dict:
                for _ in range(200):
                    line = proc.stdout.readline()
                    if not line:
                        raise ValueError("app-server exited")
                    message = json.loads(line)
                    if isinstance(message, dict) and message.get("id") == request_id:
                        if message.get("error") is not None or not isinstance(message.get("result"), dict):
                            raise ValueError("app-server rejected request")
                        return message["result"]
                raise ValueError("too many notifications")

            send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "agentbridge", "version": "1"}}})
            receive(1)
            send({"method": "initialized"})
            send({"id": 2, "method": "account/rateLimits/read"})
            return receive(2)
        finally:
            watchdog.cancel()
            proc.kill()
            proc.wait()


def _parse(result: dict) -> dict | None:
    limits = result.get("rateLimits")
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict) and isinstance(by_id.get("codex"), dict):
        limits = by_id["codex"]
    if not isinstance(limits, dict):
        return None
    parsed: dict = {"five_hour": None, "weekly": None}
    for source in ("primary", "secondary"):
        window = limits.get(source)
        if not isinstance(window, dict):
            continue
        minutes, used = window.get("windowDurationMins"), window.get("usedPercent")
        if minutes not in (300, 10080) or not isinstance(used, (int, float)):
            continue
        parsed["five_hour" if minutes == 300 else "weekly"] = {
            "used_percent": max(0, min(100, used)), "reset_at": window.get("resetsAt")}
    return parsed if parsed["five_hour"] or parsed["weekly"] else None


def _refresh() -> None:
    global _snapshot, _next_attempt, _refreshing, _error
    delay = REFRESH_SECONDS
    try:
        binary = _binary()
        if not binary:
            raise ValueError("Codex CLI not found")
        parsed = _parse(_request_rate_limits(binary))
        if not parsed:
            raise ValueError("No usable windows")
        with _lock:
            _snapshot = {**parsed, "fetched_at": time.time()}
            _error = None
    except Exception:  # noqa: BLE001 - never expose subprocess output
        delay = ERROR_SECONDS
        with _lock:
            _error = "Unable to refresh Codex usage; showing last logged values."
    finally:
        with _lock:
            _next_attempt = time.monotonic() + delay
            _refreshing = False


def live_snapshot() -> dict:
    """Return the latest live snapshot (possibly empty); start one background refresh if due."""
    global _refreshing
    with _lock:
        if time.monotonic() >= _next_attempt and not _refreshing:
            _refreshing = True
            threading.Thread(target=_refresh, daemon=True).start()
        return {**_snapshot, "refreshing": _refreshing, "refresh_error": _error}
