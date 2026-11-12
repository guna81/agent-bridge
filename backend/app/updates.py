"""Cached, best-effort checks for stable AgentBridge releases."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request

VERSION = "0.2.0"  # Development version; release builds are stamped from their tag.
RELEASES_URL = "https://github.com/guna81/llm-cli-gateway/releases/latest"
API_URL = "https://api.github.com/repos/guna81/llm-cli-gateway/releases/latest"
CACHE_SECONDS = 12 * 60 * 60
FAILURE_CACHE_SECONDS = 60 * 60
_VERSION = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def version_parts(value: str):
    match = _VERSION.fullmatch(value)
    return tuple(int(part) for part in match.groups()) if match else None


def check_update(data_dir: Path, *, force: bool = False) -> dict:
    """Return status without raising when GitHub or the cache is unavailable."""
    cache_path = data_dir / "update-check.json"
    now = time.time()
    cached = {}
    try:
        cached = json.loads(cache_path.read_text())
        checked = float(cached.get("checked_at", 0))
        ttl = CACHE_SECONDS if cached.get("latest") else FAILURE_CACHE_SECONDS
        if not 0 <= now - checked < ttl:
            cached = {}
    except (OSError, ValueError, TypeError, AttributeError):
        cached = {}
    if force or not cached:
        latest = None
        try:
            req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "AgentBridge-update-check"})
            with urllib.request.urlopen(req, timeout=2) as response:
                payload = json.loads(response.read(65536))
            tag = payload.get("tag_name")
            if isinstance(tag, str) and version_parts(tag):
                latest = tag.lstrip("v")
        except (OSError, ValueError, TypeError, AttributeError, urllib.error.URLError):
            pass
        cached = {"checked_at": now, "latest": latest}
        try:
            data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=data_dir, delete=False, encoding="utf-8") as f:
                tmp = f.name
                json.dump(cached, f)
            try:
                os.replace(tmp, cache_path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError:
            pass
    latest = cached.get("latest")
    current_parts = version_parts(VERSION)
    latest_parts = version_parts(latest) if isinstance(latest, str) else None
    return {"current": VERSION, "latest": latest if latest_parts else None,
            "available": bool(current_parts and latest_parts and latest_parts > current_parts),
            "release_url": RELEASES_URL}
