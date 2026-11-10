import contextlib
import json

from websockets.sync.client import connect

from app.runner.pty_runner import extract_urls, strip_ansi

from .conftest import FIXTURES


def test_extract_url_from_real_agy_login_screen():
    """tests/fixtures/agy_login_screen.txt is the real screen agy 1.4.x prints after choosing 'Google OAuth'."""
    urls = extract_urls(strip_ansi((FIXTURES / "agy_login_screen.txt").read_text()))
    assert len(urls) == 1
    u = urls[0]
    assert u.startswith("https://accounts.google.com/o/oauth2/auth?") and "state=" in u and "code_challenge=" in u
    assert " " not in u and "\n" not in u


def test_extract_url_rejoins_hard_wrapped_url():
    wrapped = (
        " https://accounts.google.com/o/oauth2/auth?scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinf\n"
        " o.profile+openid&state=abc123      \n"
        "\n"
        " Copy and paste the URL or click on the link below:\n"
    )
    assert extract_urls(wrapped) == ["https://accounts.google.com/o/oauth2/auth?scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile+openid&state=abc123"]


def test_extract_url_does_not_swallow_following_prose():
    assert extract_urls("visit https://a.example/x\nthen paste the code") == ["https://a.example/x"]


def test_claude_login_output_shape():
    text = ("Opening browser to sign in…\nIf the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&state=zz\n"
            "Paste code here if prompted > ")
    assert extract_urls(text) == ["https://claude.com/cai/oauth/authorize?code=true&state=zz"]


@contextlib.contextmanager
def _ws(live, name, token="test-admin-token", **q):
    """The admin token goes in the first frame, never in the URL (URLs end up in access logs)."""
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    with connect(live.base.replace("http", "ws") + f"/admin/ws/login/{name}" + (f"?{qs}" if qs else ""), open_timeout=10) as ws:
        ws.send(json.dumps({"type": "auth", "token": token}))
        yield ws


def _recv_until(ws, kind, timeout=15):
    msgs = []
    while True:
        m = json.loads(ws.recv(timeout=timeout))
        msgs.append(m)
        if m["type"] == kind:
            return msgs


def test_login_websocket_round_trip(live, login_wrapper):
    live.admin("POST", "/providers", json={"name": "oauthy", "kind": "custom", "binary_path": login_wrapper, "default_model": "x",
                                           "models": ["x"], "extra": {"login_argv": ["--login"]}})  # fmt: skip
    with _ws(live, "oauthy") as ws:
        msgs = _recv_until(ws, "url")
        url = msgs[-1]["url"]
        assert url == "https://example.com/oauth/authorize?client_id=abc&state=xyz&scope=a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q&redirect_uri=https%3A%2F%2Fexample.com%2Fcb"
        ws.send(json.dumps({"type": "input", "data": "good-code\r"}))  # relayed to the PTY
        msgs = _recv_until(ws, "exit")
    assert "Login OK for code=good-code" in "".join(m.get("data", "") for m in msgs if m["type"] == "output")
    ex = msgs[-1]
    assert ex["code"] == 0 and ex["auth"]["installed"] is True


def test_login_websocket_failure_exit_code(live, login_wrapper):
    with _ws(live, "oauthy") as ws:
        _recv_until(ws, "url")
        ws.send(json.dumps({"type": "input", "data": "wrong\r"}))
        assert _recv_until(ws, "exit")[-1]["code"] == 1


def test_login_websocket_requires_admin_token(live):
    try:
        with _ws(live, "oauthy", token="nope") as ws:
            ws.recv(timeout=5)
        assert False, "expected the server to refuse"
    except Exception as e:  # noqa: BLE001
        assert "4401" in str(e) or "closed" in str(e).lower() or "403" in str(e)


def test_login_websocket_unknown_provider_and_no_login_command(live, wrappers):
    with _ws(live, "does-not-exist") as ws:
        assert json.loads(ws.recv(timeout=5))["type"] == "error"
    with _ws(live, "txt") as ws:  # custom provider without login_argv
        assert "no login command" in json.loads(ws.recv(timeout=5))["message"]


# ---- real CLIs (opt in: RUN_REAL_CLI=1). They stop at the login prompt; nothing is authenticated. ----------------
import os
import shutil

import pytest

from app.config import get_settings

real = pytest.mark.skipif(os.environ.get("RUN_REAL_CLI") != "1", reason="set RUN_REAL_CLI=1 to run against the installed CLIs")


@real
@pytest.mark.real
@pytest.mark.skipif(not shutil.which("claude"), reason="claude not installed")
def test_real_claude_login_screen_in_isolated_config(live, monkeypatch):
    monkeypatch.setattr(get_settings(), "single_user_personal_use", True)
    live.admin("POST", "/providers", json={"name": "realclaude", "kind": "claude", "binary_path": shutil.which("claude"), "auth_mode": "oauth_cli"})
    with _ws(live, "realclaude", user_id=987) as ws:
        msgs = _recv_until(ws, "url", timeout=30)
    assert msgs[-1]["url"].startswith("https://claude.com/cai/oauth/authorize")
    st = live.admin("GET", "/providers/realclaude/status?user_id=987")
    assert st["installed"] and st["authenticated"] is False  # isolated config dir => not logged in


@real
@pytest.mark.real
@pytest.mark.skipif(not shutil.which("agy"), reason="agy not installed")
def test_real_agy_login_screen_in_isolated_home(live, monkeypatch):
    monkeypatch.setattr(get_settings(), "single_user_personal_use", True)
    live.admin("POST", "/providers", json={"name": "realagy", "kind": "agy", "binary_path": shutil.which("agy"), "auth_mode": "oauth_cli"})
    with _ws(live, "realagy", user_id=987) as ws:
        msgs = _recv_until(ws, "url", timeout=40)
    assert msgs[-1]["url"].startswith("https://accounts.google.com/o/oauth2/auth")
    st = live.admin("GET", "/providers/realagy/status?user_id=987")
    assert st["installed"] and st["authenticated"] is False and "not signed in" in st["detail"]


def test_login_websocket_ignores_token_in_url(live):
    """A token in the query string must not authenticate: the first frame has to be the auth message."""
    try:
        with connect(live.base.replace("http", "ws") + "/admin/ws/login/oauthy?token=test-admin-token", open_timeout=10) as ws:
            ws.send(json.dumps({"type": "input", "data": "x"}))
            ws.recv(timeout=5)
        assert False, "expected the server to refuse"
    except Exception as e:  # noqa: BLE001
        assert "4401" in str(e) or "closed" in str(e).lower()
