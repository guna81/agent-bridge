import asyncio
import json
import stat
import sys

import httpx
import pytest

from app.codex_discovery import DiscoveryError, _request_models, discover_models
from app.models import Provider
from app.provider_models import provider_models


def make_server(tmp_path, behavior="success"):
    script = tmp_path / "codex"
    script.write_text(f'''#!{sys.executable}
import json, sys
if sys.argv[1:] == ["login", "status"]:
    sys.exit(1 if {behavior!r} == "logged_out" else 0)
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        print(json.dumps({{"method": "notification"}}), flush=True)
        print(json.dumps({{"id": msg["id"], "result": {{}}}}), flush=True)
    elif msg.get("method") == "model/list":
        if {behavior!r} == "error":
            print(json.dumps({{"id": msg["id"], "error": {{"message": "secret"}}}}), flush=True)
            continue
        cursor = msg["params"].get("cursor")
        data = [{{"model": "gpt-one", "hidden": False}}, {{"model": "secret-model", "hidden": True}}] if not cursor else [{{"model": "gpt-two"}}, {{"model": "gpt-one"}}]
        print(json.dumps({{"id": msg["id"], "result": {{"data": data, "nextCursor": "page2" if not cursor else None}}}}), flush=True)
''')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.asyncio
async def test_protocol_pagination_filters_and_deduplicates(tmp_path):
    binary = make_server(tmp_path)
    assert await _request_models(binary, {}, tmp_path) == ["gpt-one", "gpt-two"]


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["error", "logged_out"])
async def test_protocol_errors_are_safe(tmp_path, behavior):
    binary = make_server(tmp_path, behavior)
    with pytest.raises(DiscoveryError) as exc:
        await _request_models(binary, {}, tmp_path)
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_discovery_does_not_use_isolated_user_credentials():
    p = Provider(name="codex", kind="codex", enabled=True, backend="cli", auth_mode="oauth_cli", use_host_home=False)
    with pytest.raises(DiscoveryError, match="shared host login"):
        await discover_models(p)


def test_model_union_keeps_manual_and_default():
    p = Provider(kind="codex", models=["default", "manual"], default_model="default", extra={"discovered_models": ["manual", "gpt-one"]})
    assert provider_models(p) == ["default", "manual", "gpt-one"]


def test_discovered_models_are_routable_and_key_filtered(live):
    from app.db import session_scope
    from app.models import Provider as Model
    from sqlalchemy import select
    from tests.conftest import ADMIN

    with session_scope() as s:
        p = s.scalar(select(Model).where(Model.name == "codex"))
        original_models, original_extra = p.models, p.extra
        p.models = ["default"]
        p.extra = {**(p.extra or {}), "discovered_models": ["test-discovered"]}
    try:
        result = httpx.get(live.v1 + "/models", headers={"Authorization": "Bearer " + live.key}, timeout=10).json()
        assert "codex/test-discovered" in [m["id"] for m in result["data"]]
        from app.api.common import resolve_provider
        assert resolve_provider("codex/test-discovered")[1] == "test-discovered"
        key = live.admin("POST", "/keys", json={"user_id": live.user_id, "allowed_models": ["codex/default"]})
        result = httpx.get(live.v1 + "/models", headers={"Authorization": "Bearer " + key["key"]}, timeout=10).json()
        assert "codex/test-discovered" not in [m["id"] for m in result["data"]]
        assert httpx.post(live.base + "/admin/providers/codex/discover-models", timeout=10).status_code in (401, 403)
        # An ineligible provider fails without erasing previously discovered models.
        r = httpx.post(live.base + "/admin/providers/codex/discover-models", headers=ADMIN, timeout=10)
        assert r.status_code == 400
        provider = next(x for x in live.admin("GET", "/providers") if x["name"] == "codex")
        assert provider["extra"]["discovered_models"] == ["test-discovered"]
    finally:
        with session_scope() as s:
            p = s.scalar(select(Model).where(Model.name == "codex"))
            p.models, p.extra = original_models, original_extra
