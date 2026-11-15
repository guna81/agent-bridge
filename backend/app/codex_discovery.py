"""Discover the host Codex account's picker models through its app-server protocol."""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from pathlib import Path

from sqlalchemy import select

from .adapters.codex import CodexAdapter
from .adapters.base import RunContext, resolve_binary
from .db import session_scope
from .models import Provider
from .runner.env import build_env, host_home
from .runner.workdir import fresh_workdir


class DiscoveryError(Exception):
    """A safe-to-display discovery failure (never includes subprocess output)."""


def eligible(p: Provider) -> bool:
    # Discovery is global, so it must not use one isolated user's credentials for all users.
    return bool(p.kind == "codex" and p.enabled and p.backend == "cli" and p.auth_mode == "oauth_cli" and p.use_host_home)


def fingerprint(p: Provider) -> tuple:
    return (p.kind, p.enabled, p.backend, p.auth_mode, p.use_host_home, p.binary_path, p.mode, p.api_key_enc)


async def discover_models(p: Provider) -> list[str]:
    if not eligible(p):
        raise DiscoveryError("Discovery requires an enabled Codex CLI provider using the shared host login.")
    binary = resolve_binary(p.binary_path or p.kind)
    if not binary:
        raise DiscoveryError("Codex CLI was not found.")
    with fresh_workdir() as wd:
        ctx = RunContext(provider_name=p.name, mode=p.mode, auth_mode=p.auth_mode, workdir=wd,
                         home=Path(host_home()), binary=binary, raw_system_prompt=p.raw_system_prompt,
                         use_host_home=True, extra=dict(p.extra or {}))
        env = build_env(ctx, CodexAdapter()._env(ctx))
        try:
            async with asyncio.timeout(30):
                return await _request_models(binary, env, wd)
        except TimeoutError:
            raise DiscoveryError("Codex model discovery timed out.") from None
        except (OSError, ValueError, json.JSONDecodeError, asyncio.LimitOverrunError):
            raise DiscoveryError("Codex model discovery failed; check the CLI and its login.") from None


async def _request_models(binary: str, env: dict[str, str], cwd: Path) -> list[str]:
    status = await asyncio.create_subprocess_exec(binary, "login", "status", cwd=str(cwd), env=env,
                                                  stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        if await status.wait() != 0:
            raise DiscoveryError("Codex is not logged in; existing models were retained.")
    finally:
        if status.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                status.kill()
            await status.wait()
    proc = await asyncio.create_subprocess_exec(binary, "app-server", "--stdio", cwd=str(cwd), env=env,
                                                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024)
    assert proc.stdin and proc.stdout

    async def send(message: dict) -> None:
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()

    async def receive(request_id: int) -> dict:
        for _ in range(200):
            line = await proc.stdout.readline()
            if not line:
                raise DiscoveryError("Codex app-server exited during model discovery.")
            message = json.loads(line)
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if message.get("error") is not None or not isinstance(message.get("result"), dict):
                raise DiscoveryError("Codex app-server could not list models; check its login.")
            return message["result"]
        raise DiscoveryError("Codex app-server sent too many notifications.")

    try:
        await send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "agentbridge", "version": "1"}}})
        await receive(1)
        await send({"method": "initialized"})
        models: list[str] = []
        cursor = None
        seen: set[str] = set()
        for page in range(20):
            await send({"id": page + 2, "method": "model/list", "params": {"includeHidden": False, "limit": 100, "cursor": cursor}})
            result = await receive(page + 2)
            data = result.get("data")
            if not isinstance(data, list):
                raise DiscoveryError("Codex app-server returned an invalid model list.")
            for entry in data:
                if not isinstance(entry, dict):
                    raise DiscoveryError("Codex app-server returned an invalid model list.")
                slug = entry.get("model")
                if not entry.get("hidden", False) and isinstance(slug, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", slug):
                    models.append(slug)
            cursor = result.get("nextCursor")
            if cursor is None:
                if not models:
                    raise DiscoveryError("Codex returned no visible models; existing models were retained.")
                return list(dict.fromkeys(models))
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise DiscoveryError("Codex returned invalid pagination information.")
            seen.add(cursor)
        raise DiscoveryError("Codex model list exceeded the page limit.")
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


async def refresh_provider(name: str) -> list[str]:
    with session_scope() as session:
        p = session.scalar(select(Provider).where(Provider.name == name))
        if p is None:
            raise DiscoveryError("Provider not found.")
        expected = fingerprint(p)
        session.expunge(p)
    models = await discover_models(p)
    with session_scope() as session:
        current = session.scalar(select(Provider).where(Provider.name == name))
        if current is None or fingerprint(current) != expected:
            raise DiscoveryError("Provider settings changed during discovery; please retry.")
        current.extra = {**(current.extra or {}), "discovered_models": models}
    return models
