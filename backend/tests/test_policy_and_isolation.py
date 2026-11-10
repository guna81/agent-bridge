import json

import httpx
import openai
import pytest
from openai import OpenAI

from app.config import get_settings
from app.errors import ProxyError
from app.ratelimit import RateLimiter

MSG = [{"role": "user", "content": "hi"}]


def test_admin_requires_token(live):
    assert httpx.get(live.base + "/admin/providers").status_code == 401
    assert httpx.get(live.base + "/admin/providers", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert httpx.get(live.base + "/admin/providers", headers={"Authorization": f"Bearer {live.key}"}).status_code == 401  # a proxy key is not an admin token


def test_provider_api_key_encrypted_at_rest_and_never_returned(live):
    secret = "sk-ant-SUPER-SECRET-123"
    live.admin("POST", "/providers", json={"name": "keyed", "kind": "custom", "binary_path": "/bin/true"})
    out = live.admin("PUT", "/providers/keyed/secret", json={"api_key": secret})
    assert out == {"has_api_key": True}
    assert secret not in json.dumps(live.admin("GET", "/providers"))
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Provider
    from app.security import decrypt_secret

    with session_scope() as s:
        enc = s.scalar(select(Provider.api_key_enc).where(Provider.name == "keyed"))
    assert enc and secret not in enc and decrypt_secret(enc) == secret


def test_oauth_mode_requires_single_user_flag(live, monkeypatch):
    monkeypatch.setattr(get_settings(), "single_user_personal_use", False)
    r = httpx.put(live.base + "/admin/providers/claude", headers={"Authorization": "Bearer test-admin-token"}, json={"auth_mode": "oauth_cli"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "oauth_disabled"
    r = httpx.put(live.base + "/admin/providers/claude", headers={"Authorization": "Bearer test-admin-token"}, json={"use_host_home": True})
    assert r.status_code == 400
    monkeypatch.setattr(get_settings(), "single_user_personal_use", True)
    r = httpx.put(live.base + "/admin/providers/claude", headers={"Authorization": "Bearer test-admin-token"}, json={"auth_mode": "oauth_cli"})
    assert r.status_code == 200
    # restore
    httpx.put(live.base + "/admin/providers/claude", headers={"Authorization": "Bearer test-admin-token"}, json={"auth_mode": "api_key"})


def test_oauth_provider_refuses_to_run_when_flag_off(live, monkeypatch):
    monkeypatch.setattr(get_settings(), "single_user_personal_use", True)
    live.admin("PUT", "/providers/agy", json={"auth_mode": "oauth_cli"})
    monkeypatch.setattr(get_settings(), "single_user_personal_use", False)  # flag flipped off after the fact
    try:
        with pytest.raises(openai.PermissionDeniedError) as e:
            OpenAI(base_url=live.v1, api_key=live.key, max_retries=0).chat.completions.create(model="agy/gemini-3.8-flash-low", messages=MSG)
        assert e.value.body["code"] == "oauth_disabled"
    finally:
        monkeypatch.setattr(get_settings(), "single_user_personal_use", True)
        live.admin("PUT", "/providers/agy", json={"auth_mode": "api_key"})


def test_skip_permissions_rejected_in_raw_mode(live):
    r = httpx.put(live.base + "/admin/providers/claude", headers={"Authorization": "Bearer test-admin-token"}, json={"mode": "raw", "skip_permissions": True})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_combination"


def test_disabled_provider_is_not_listed_or_callable(live):
    live.admin("PUT", "/providers/txt", json={"enabled": False})
    try:
        ids = {m.id for m in OpenAI(base_url=live.v1, api_key=live.key).models.list().data}
        assert "txt/t1" not in ids
        with pytest.raises(openai.NotFoundError):
            OpenAI(base_url=live.v1, api_key=live.key, max_retries=0).chat.completions.create(model="txt/t1", messages=MSG)
    finally:
        live.admin("PUT", "/providers/txt", json={"enabled": True})


def test_cli_sees_a_minimal_environment_without_server_secrets(live, wrappers):
    """Run /usr/bin/env as the 'CLI' and look at what it was given."""
    live.admin("POST", "/providers", json={
        "name": "envdump", "kind": "custom", "enabled": True, "binary_path": "/usr/bin/env", "default_model": "e", "models": ["e"],
        "extra": {"args_template": [], "output_format": "text"}})  # fmt: skip
    text = OpenAI(base_url=live.v1, api_key=live.key).chat.completions.create(model="envdump/e", messages=MSG).choices[0].message.content
    env = dict(l.split("=", 1) for l in text.splitlines() if "=" in l)
    assert not [k for k in env if k.startswith("PROXY_")], "server settings leaked into CLI env"
    assert "test-admin-token" not in text and "Hmb0qXbsQZ0cT4o" not in text
    assert env["HOME"].startswith(str(get_settings().data_dir)), "HOME must be the isolated per-user dir"
    assert set(env) <= {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "TMPDIR", "NO_COLOR", "CI", "PWD", "SHLVL", "_", "OLDPWD"}


def test_workdir_is_fresh_and_deleted(live):
    live.admin("POST", "/providers", json={
        "name": "pwdcli", "kind": "custom", "enabled": True, "binary_path": "/bin/pwd", "default_model": "p", "models": ["p"],
        "extra": {"args_template": [], "output_format": "text"}})  # fmt: skip
    c = OpenAI(base_url=live.v1, api_key=live.key)
    a = c.chat.completions.create(model="pwdcli/p", messages=MSG).choices[0].message.content.strip()
    b = c.chat.completions.create(model="pwdcli/p", messages=MSG).choices[0].message.content.strip()
    import os

    assert a != b and "run-" in a
    assert not os.path.exists(a) and not os.path.exists(b)


def test_rate_limiter():
    rl = RateLimiter(2)
    rl.check(1)
    rl.check(1)
    with pytest.raises(ProxyError) as e:
        rl.check(1)
    assert e.value.status == 429 and "Retry-After" in e.value.headers
    rl.check(2)  # per-key


def test_logs_do_not_contain_prompts_by_default(live):
    import logging

    from app.logging_setup import JsonFormatter

    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, record):
            lines.append(JsonFormatter().format(record))

    h = H()
    logging.getLogger("proxy").addHandler(h)
    try:
        OpenAI(base_url=live.v1, api_key=live.key).chat.completions.create(model="claude/sonnet", messages=[{"role": "user", "content": "SENTINEL-PROMPT-TEXT"}])
    finally:
        logging.getLogger("proxy").removeHandler(h)
    joined = "\n".join(lines)
    assert "chat.finished" in joined and "SENTINEL-PROMPT-TEXT" not in joined
