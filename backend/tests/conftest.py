import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
FAKE = HERE / "fake_cli.py"

# Must be set before the app package reads settings.
_tmp = tempfile.mkdtemp(prefix="proxy-test-")
os.environ.update({
    "PROXY_DATA_DIR": _tmp,
    "PROXY_SECRET_KEY": "Hmb0qXbsQZ0cT4oNnVfm2xUe2m9N0m3m1x0yq0rB3dM=",
    "PROXY_ADMIN_TOKEN": "test-admin-token",
    "PROXY_KEY_PEPPER": "test-pepper",
    "PROXY_RATE_LIMIT_PER_MINUTE": "1000",
    "PROXY_QUEUE_TIMEOUT_S": "2",
    "PROXY_REQUEST_TIMEOUT_S": "20",
})


def make_wrapper(dirpath: Path, flavor: str) -> str:
    """Executable that runs fake_cli.py with the given flavor (so binary_path can be a single path)."""
    w = dirpath / f"fake-{flavor}"
    w.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" --flavor={flavor} "$@"\n')
    w.chmod(w.stat().st_mode | stat.S_IEXEC)
    return str(w)


@pytest.fixture(scope="session")
def wrappers(tmp_path_factory) -> dict[str, str]:
    d = tmp_path_factory.mktemp("bin")
    return {f: make_wrapper(d, f) for f in ("claude", "agy", "codex", "gemini", "text", "ndjson", "json")}


# ---- live server ------------------------------------------------------------------------------
import socket
import threading
import time

import httpx
import uvicorn

LIVE_APP = None
ADMIN = {"Authorization": "Bearer test-admin-token"}


class Live:
    def __init__(self, base: str, key: str, user_id: int, wrappers: dict[str, str]):
        self.base, self.key, self.user_id, self.wrappers = base, key, user_id, wrappers

    @property
    def v1(self) -> str:
        return self.base + "/v1"

    def admin(self, method: str, path: str, **kw):
        r = httpx.request(method, self.base + "/admin" + path, headers=ADMIN, timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def new_user(self, name: str, credits: float = 5.0) -> tuple[int, str]:
        u = self.admin("POST", "/users", json={"name": name, "credits_usd": credits})
        k = self.admin("POST", "/keys", json={"user_id": u["id"], "label": name})
        return u["id"], k["key"]


@pytest.fixture(scope="session")
def live(wrappers):
    from app.main import create_app

    global LIVE_APP
    app = LIVE_APP = create_app()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("server did not start")

    lv = Live(base, "", 0, wrappers)
    lv.user_id, lv.key = lv.new_user("tester", 5.0)
    common = {"enabled": True, "mode": "raw", "auth_mode": "api_key"}
    lv.admin("PUT", "/providers/claude", json={**common, "binary_path": wrappers["claude"]})
    lv.admin("PUT", "/providers/agy", json={**common, "binary_path": wrappers["agy"]})
    lv.admin("PUT", "/providers/codex", json={**common, "binary_path": wrappers["codex"]})
    lv.admin("PUT", "/providers/gemini", json={**common, "binary_path": wrappers["gemini"]})
    lv.admin("POST", "/providers", json={
        "name": "txt", "kind": "custom", **common, "binary_path": wrappers["text"], "default_model": "t1", "models": ["t1"],
        "extra": {"args_template": ["{prompt}"], "output_format": "text"}})  # fmt: skip
    yield lv
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture(scope="session")
def login_wrapper(tmp_path_factory) -> str:
    d = tmp_path_factory.mktemp("loginbin")
    w = d / "fake-login"
    w.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fake_login.py"}" "$@"\n')
    w.chmod(w.stat().st_mode | stat.S_IEXEC)
    return str(w)
