import httpx
import pytest
from sqlalchemy import select

from app import codex_discovery
from app.db import session_scope
from app.models import Provider
from tests.conftest import ADMIN


def test_refresh_endpoint_keeps_manual_models_and_manages_discovered(live, monkeypatch):
    async def fake_discovery(provider):
        return ["gpt-new", "gpt-other"]

    monkeypatch.setattr(codex_discovery, "discover_models", fake_discovery)
    with session_scope() as session:
        p = session.scalar(select(Provider).where(Provider.name == "codex"))
        original_models, original_extra = p.models, p.extra
        p.models, p.extra = ["default", "custom"], {"discovered_models": ["old"]}
    try:
        response = httpx.post(live.base + "/admin/providers/codex/discover-models", headers=ADMIN, timeout=10)
        assert response.status_code == 200
        assert response.json()["models"] == ["default", "custom"]
        assert response.json()["extra"]["discovered_models"] == ["gpt-new", "gpt-other"]
        # The normal settings editor cannot inject or erase the server-managed list.
        updated = live.admin("PUT", "/providers/codex", json={"extra": {"discovered_models": ["injected"], "sandbox": "read-only"}})
        assert updated["extra"] == {"discovered_models": ["gpt-new", "gpt-other"], "sandbox": "read-only"}
    finally:
        with session_scope() as session:
            p = session.scalar(select(Provider).where(Provider.name == "codex"))
            p.models, p.extra = original_models, original_extra


@pytest.mark.asyncio
async def test_refresh_does_not_save_when_provider_settings_change(live, monkeypatch):
    async def change_provider(provider):
        with session_scope() as session:
            p = session.scalar(select(Provider).where(Provider.name == "codex"))
            p.binary_path = "changed-while-discovering"
        return ["gpt-new"]

    with session_scope() as session:
        p = session.scalar(select(Provider).where(Provider.name == "codex"))
        original_binary, original_extra = p.binary_path, p.extra
        p.extra = {"discovered_models": ["old"]}
    monkeypatch.setattr(codex_discovery, "discover_models", change_provider)
    try:
        with pytest.raises(codex_discovery.DiscoveryError, match="settings changed"):
            await codex_discovery.refresh_provider("codex")
        with session_scope() as session:
            p = session.scalar(select(Provider).where(Provider.name == "codex"))
            assert p.extra["discovered_models"] == ["old"]
    finally:
        with session_scope() as session:
            p = session.scalar(select(Provider).where(Provider.name == "codex"))
            p.binary_path, p.extra = original_binary, original_extra
