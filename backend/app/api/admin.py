from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import ledger
from ..adapters.base import Done, Error, NormalizedRequest, RunContext, TextDelta, Usage
from ..adapters.registry import ADAPTERS, new_adapter
from ..config import get_settings
from ..db import session_scope
from ..errors import ProxyError
from ..models import ApiKey, Provider, Reservation, User, iso_utc
from ..runner.env import host_home
from ..runner.workdir import fresh_workdir, user_home
from ..security import encrypt_secret, generate_proxy_key, hash_proxy_key, key_display_prefix
from ..service import run_chat
from .deps import require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/update-status")
async def update_status():
    from ..updates import check_update
    return await asyncio.to_thread(check_update, get_settings().data_dir)


@router.get("/reservations")
async def list_reservations():
    with session_scope() as s:
        return [{"request_id": r.request_id, "user_id": r.user_id, "key_id": r.key_id,
                 "amount_usd": r.amount_usd, "created_at": iso_utc(r.created_at)}
                for r in s.scalars(select(Reservation).order_by(Reservation.created_at))]


@router.delete("/reservations/{request_id}")
async def release_reservation(request_id: str):
    if not ledger.release_reservation(request_id):
        raise ProxyError(404, "Reservation not found", code="not_found")
    return {"released": request_id}

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


# ---------- providers ----------------------------------------------------------------------------
def provider_out(p: Provider) -> dict:
    return {
        "name": p.name, "kind": p.kind, "enabled": p.enabled, "backend": p.backend, "binary_path": p.binary_path,
        "default_model": p.default_model, "models": p.models or [], "mode": p.mode, "auth_mode": p.auth_mode,
        "raw_system_prompt": p.raw_system_prompt, "skip_permissions": p.skip_permissions,
        "use_host_home": p.use_host_home, "max_budget_usd": p.max_budget_usd, "extra": p.extra or {},
        "has_api_key": bool(p.api_key_enc),
    }  # fmt: skip


class ProviderPatch(BaseModel):
    enabled: bool | None = None
    backend: str | None = Field(None, pattern="^(cli|direct)$")
    binary_path: str | None = None
    default_model: str | None = None
    models: list[str] | None = None
    mode: str | None = Field(None, pattern="^(raw|agent)$")
    auth_mode: str | None = Field(None, pattern="^(api_key|oauth_cli)$")
    raw_system_prompt: str | None = None
    skip_permissions: bool | None = None
    use_host_home: bool | None = None
    max_budget_usd: float | None = Field(None, gt=0)
    extra: dict | None = None


class ProviderCreate(ProviderPatch):
    name: str
    kind: str = "custom"


def _apply(p: Provider, patch: ProviderPatch) -> None:
    from ..codex_discovery import fingerprint

    s = get_settings()
    old_fingerprint = fingerprint(p)
    data = patch.model_dump(exclude_unset=True)
    if "extra" in data and p.kind == "codex":
        # Discovery is managed by the server, not editable provider extras.
        discovered = (p.extra or {}).get("discovered_models")
        data["extra"] = {k: v for k, v in (data["extra"] or {}).items() if k != "discovered_models"}
        if discovered is not None:
            data["extra"]["discovered_models"] = discovered
    for k, v in data.items():
        if k in ("name", "kind"):
            continue
        setattr(p, k, v)
    if p.kind == "codex" and fingerprint(p) != old_fingerprint:
        p.extra = {k: v for k, v in (p.extra or {}).items() if k != "discovered_models"}
    if p.auth_mode == "oauth_cli" and not s.single_user_personal_use:
        raise ProxyError(400, "oauth_cli requires PROXY_SINGLE_USER_PERSONAL_USE=true (consumer-subscription OAuth is for "
                              "single-user personal use only).", code="oauth_disabled")  # fmt: skip
    if p.use_host_home and not s.single_user_personal_use:
        raise ProxyError(400, "use_host_home requires PROXY_SINGLE_USER_PERSONAL_USE=true.", code="oauth_disabled")
    if p.skip_permissions and p.mode != "agent":
        raise ProxyError(400, "skip_permissions is only allowed in agent mode (never in raw mode).", code="invalid_combination")


def _get_provider(s, name: str) -> Provider:  # noqa: ANN001
    p = s.scalar(select(Provider).where(Provider.name == name))
    if p is None:
        raise ProxyError(404, f"Unknown provider {name!r}", code="not_found")
    return p


@router.get("/settings")
async def get_admin_settings(request: Request):
    s = get_settings()
    return {
        "single_user_personal_use": s.single_user_personal_use,
        "queue": request.app.state.service.queue.stats(),
        "limits": {"max_concurrency": s.max_concurrency, "per_user_concurrency": s.per_user_concurrency,
                   "rate_limit_per_minute": s.rate_limit_per_minute, "max_body_bytes": s.max_body_bytes},  # fmt: skip
        "adapter_kinds": sorted(ADAPTERS),
    }


@router.get("/status-bar/config")
async def get_status_bar_config():
    from ..status_bar_config import load_status_bar_config
    return load_status_bar_config().model_dump()


@router.post("/status-bar/config")
async def update_status_bar_config(body: dict):
    from ..status_bar_config import StatusBarConfig, load_status_bar_config, save_status_bar_config
    try:
        current = load_status_bar_config().model_dump()
        current.update(body)
        new_cfg = StatusBarConfig.model_validate(current)
    except Exception as e:
        raise ProxyError(400, f"Invalid configuration: {e}", code="invalid_config")
    save_status_bar_config(new_cfg)
    return new_cfg.model_dump()


@router.get("/status-bar")
async def get_status_bar_data(request: Request):
    from ..rate_limits_reader import get_all_cli_rate_limits
    from ..status_bar_config import load_status_bar_config

    s = get_settings()
    stats = ledger.provider_usage_stats()
    cli_limits = get_all_cli_rate_limits()
    cfg = load_status_bar_config()
    with session_scope() as sess:
        providers = list(sess.scalars(select(Provider).order_by(Provider.id)))
        provider_list = []
        for p in providers:
            p_stat = stats["by_provider"].get(p.name, {
                "lifetime_cost_usd": 0.0, "lifetime_requests": 0,
                "lifetime_input_tokens": 0, "lifetime_output_tokens": 0,
                "today_cost_usd": 0.0, "today_requests": 0,
                "seven_days_cost_usd": 0.0, "seven_days_requests": 0,
            })
            provider_list.append({
                "name": p.name,
                "kind": p.kind,
                "enabled": p.enabled,
                "max_budget_usd": p.max_budget_usd,
                **p_stat,
            })

    return {
        "online": True,
        "port": s.port,
        "queue": request.app.state.service.queue.stats(),
        "providers": provider_list,
        "totals": stats["totals"],
        "credits_remaining_usd": stats["credits_remaining_usd"],
        "rate_limits": cli_limits,
        "config": cfg.model_dump(),
    }


@router.get("/providers")
async def list_providers():
    with session_scope() as s:
        return [provider_out(p) for p in s.scalars(select(Provider).order_by(Provider.id))]


@router.post("/providers")
async def create_provider(body: ProviderCreate):
    if not NAME_RE.match(body.name):
        raise ProxyError(400, "name must match [a-z0-9][a-z0-9_-]{0,31}", code="invalid_name")
    if body.kind not in ADAPTERS:
        raise ProxyError(400, f"kind must be one of {sorted(ADAPTERS)}", code="invalid_kind")
    with session_scope() as s:
        if s.scalar(select(Provider).where(Provider.name == body.name)):
            raise ProxyError(409, "provider already exists", code="exists")
        p = Provider(name=body.name, kind=body.kind, mode="raw", auth_mode="api_key", models=[], extra={})
        _apply(p, body)
        s.add(p)
        s.flush()
        return provider_out(p)


@router.put("/providers/{name}")
async def update_provider(name: str, body: ProviderPatch):
    with session_scope() as s:
        p = _get_provider(s, name)
        _apply(p, body)
        s.flush()
        return provider_out(p)


@router.delete("/providers/{name}")
async def delete_provider(name: str):
    with session_scope() as s:
        p = _get_provider(s, name)
        if p.kind != "custom":
            raise ProxyError(400, "built-in providers cannot be deleted; disable them instead", code="builtin")
        s.delete(p)
    return {"deleted": name}


class SecretBody(BaseModel):
    api_key: str


@router.put("/providers/{name}/secret")
async def set_secret(name: str, body: SecretBody):
    with session_scope() as s:
        p = _get_provider(s, name)
        p.api_key_enc = encrypt_secret(body.api_key) if body.api_key else ""
        return {"has_api_key": bool(p.api_key_enc)}


def _ctx_for_status(p: Provider, wd: Path, user_id: int) -> RunContext:
    from ..security import decrypt_secret

    return RunContext(
        provider_name=p.name, mode=p.mode, auth_mode=p.auth_mode, workdir=wd,  # type: ignore[arg-type]
        home=Path(host_home()) if p.use_host_home else user_home(p.name, user_id),
        binary=p.binary_path or p.kind, raw_system_prompt=p.raw_system_prompt,
        api_key=decrypt_secret(p.api_key_enc) if p.api_key_enc else None,
        use_host_home=p.use_host_home, extra=dict(p.extra or {}),
    )  # fmt: skip


@router.get("/providers/{name}/status")
async def provider_status(name: str, user_id: int = Query(0)):
    with session_scope() as s:
        p = _get_provider(s, name)
        s.expunge(p)
    if p.backend == "direct":
        return {"installed": True, "version": None, "authenticated": bool(p.api_key_enc), "detail": "direct API backend (no CLI)"}

    def probe():
        with fresh_workdir() as wd:
            st = new_adapter(p.kind).auth_status(_ctx_for_status(p, wd, user_id))
            return {"installed": st.installed, "version": st.version, "authenticated": st.authenticated, "detail": st.detail}

    return await asyncio.to_thread(probe)


class TestBody(BaseModel):
    prompt: str = "Say hello in five words."
    model: str | None = None


@router.post("/providers/{name}/discover-models")
async def discover_provider_models(name: str):
    from ..codex_discovery import DiscoveryError, refresh_provider

    try:
        await refresh_provider(name)
    except DiscoveryError as exc:
        raise ProxyError(400, str(exc), code="model_discovery_failed") from None
    with session_scope() as s:
        return provider_out(_get_provider(s, name))


@router.post("/providers/{name}/test")
async def test_provider(name: str, body: TestBody, request: Request):
    """One-shot prompt, unbilled. Returns the parsed answer AND the raw CLI output lines."""
    with session_scope() as s:
        p = _get_provider(s, name)
        s.expunge(p)
    req = NormalizedRequest(model=body.model or p.default_model, system="", turns=[("user", body.prompt)])
    raw: list[str] = []
    text: list[str] = []
    usage = None
    error = None
    finish = None
    t0 = time.monotonic()
    gen = run_chat(request.app.state.service, p, None, req, "test-" + uuid.uuid4().hex[:12], raw_sink=raw)
    try:
        async for ev in gen:
            if isinstance(ev, TextDelta):
                text.append(ev.text)
            elif isinstance(ev, Usage):
                usage = {"input_tokens": ev.input_tokens, "output_tokens": ev.output_tokens, "cost_usd": ev.cost_usd}
            elif isinstance(ev, Done):
                finish = ev.finish_reason
            elif isinstance(ev, Error):
                error = {"code": ev.code, "message": ev.message}
    except ProxyError as e:
        error = {"code": e.code, "message": e.message}
    finally:
        await gen.aclose()
    return {"ok": error is None, "text": "".join(text), "usage": usage, "finish_reason": finish, "error": error,
            "duration_ms": int((time.monotonic() - t0) * 1000), "raw_lines": raw}  # fmt: skip


# ---------- users / keys / credits ---------------------------------------------------------------
class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    credits_usd: float = Field(0.0, ge=0)


@router.get("/users")
async def list_users():
    with session_scope() as s:
        users = list(s.scalars(select(User).order_by(User.id)))
    return [{"id": u.id, "name": u.name, **ledger.usage_summary(u.id)} for u in users]


@router.post("/users")
async def create_user(body: UserCreate):
    with session_scope() as s:
        if s.scalar(select(User).where(User.name == body.name)):
            raise ProxyError(409, "user already exists", code="exists")
        u = User(name=body.name, credits_usd=body.credits_usd)
        s.add(u)
        s.flush()
        return {"id": u.id, "name": u.name, "credits_usd": u.credits_usd}


class TopUpBody(BaseModel):
    amount_usd: float
    note: str = ""


@router.post("/users/{user_id}/topup")
async def topup(user_id: int, body: TopUpBody):
    with session_scope() as s:
        if s.get(User, user_id) is None:
            raise ProxyError(404, "unknown user", code="not_found")
    return {"user_id": user_id, "credits_usd": ledger.top_up(user_id, body.amount_usd, body.note)}


@router.get("/ledger")
async def get_ledger(user_id: int | None = None, limit: int = Query(100, ge=1, le=1000),
                     key_id: int | None = None, provider: str | None = None, model: str | None = None,
                     start: dt.datetime | None = None, end: dt.datetime | None = None,
                     before_id: int | None = Query(None, ge=1)):
    return ledger.recent(user_id, limit, key_id=key_id, provider=provider, model=model,
                         start=start, end=end, before_id=before_id)


@router.get("/usage/daily")
async def usage_daily(days: int = Query(14, ge=1, le=90)):
    return ledger.daily_usage(days)


class KeyCreate(BaseModel):
    user_id: int
    label: str = ""
    budget_usd: float | None = Field(None, gt=0)  # lifetime spending cap for this key
    daily_budget_usd: float | None = Field(None, gt=0)
    monthly_budget_usd: float | None = Field(None, gt=0)
    expires_at: dt.datetime | None = None  # ISO-8601; a value without an offset is taken as UTC
    expires_in_days: float | None = Field(None, gt=0)  # convenience alternative to expires_at
    allowed_models: list[str] | None = None  # exact ids or globs, e.g. ["claude/haiku", "agy/*"]


class KeyPatch(BaseModel):
    label: str | None = None
    budget_usd: float | None = Field(None, gt=0)
    daily_budget_usd: float | None = Field(None, gt=0)
    monthly_budget_usd: float | None = Field(None, gt=0)
    expires_at: dt.datetime | None = None
    allowed_models: list[str] | None = None


def _utc(d: dt.datetime | None) -> dt.datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _clean_models(models: list[str] | None) -> list[str] | None:
    out = [m.strip() for m in models or [] if m and m.strip()]
    return out or None


def key_out(k: ApiKey, u: User | None, spent: float) -> dict:
    return {"id": k.id, "user_id": k.user_id, "user": u.name if u else "?", "label": k.label, "prefix": k.prefix,
            "revoked": k.revoked, "created_at": iso_utc(k.created_at), "last_used_at": iso_utc(k.last_used_at),
            "credits_usd": u.credits_usd if u else 0.0, "budget_usd": k.budget_usd, "spent_usd": spent,
            "daily_budget_usd": k.daily_budget_usd, "monthly_budget_usd": k.monthly_budget_usd,
            "daily_spent_usd": ledger.key_period_spent(k.id, "daily"), "monthly_spent_usd": ledger.key_period_spent(k.id, "monthly"),
            "expires_at": iso_utc(k.expires_at), "allowed_models": k.allowed_models or []}  # fmt: skip


@router.get("/keys")
async def list_keys():
    with session_scope() as s:
        rows = [(k, s.get(User, k.user_id)) for k in s.scalars(select(ApiKey).order_by(ApiKey.id))]
        spent = ledger.keys_spent()
        return [key_out(k, u, spent.get(k.id, 0.0)) for k, u in rows]


@router.post("/keys")
async def create_key(body: KeyCreate):
    key = generate_proxy_key()
    with session_scope() as s:
        if s.get(User, body.user_id) is None:
            raise ProxyError(404, "unknown user", code="not_found")
        expires = _utc(body.expires_at)
        if expires is None and body.expires_in_days:
            expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=body.expires_in_days)
        k = ApiKey(user_id=body.user_id, label=body.label, prefix=key_display_prefix(key), key_hash=hash_proxy_key(key),
                   budget_usd=body.budget_usd, daily_budget_usd=body.daily_budget_usd, monthly_budget_usd=body.monthly_budget_usd, expires_at=expires, allowed_models=_clean_models(body.allowed_models))  # fmt: skip
        s.add(k)
        s.flush()
        return {"id": k.id, "key": key, "prefix": k.prefix, "budget_usd": k.budget_usd, "expires_at": iso_utc(k.expires_at),
                "allowed_models": k.allowed_models or [], "note": "Store this key now; it cannot be shown again."}  # fmt: skip


@router.patch("/keys/{key_id}")
async def update_key(key_id: int, body: KeyPatch):
    """Change a key's limits. Send a field as null to clear that limit; omit it to leave it alone."""
    data = body.model_dump(exclude_unset=True)
    with session_scope() as s:
        k = s.get(ApiKey, key_id)
        if k is None:
            raise ProxyError(404, "unknown key", code="not_found")
        if "label" in data:
            k.label = data["label"] or ""
        if "budget_usd" in data:
            k.budget_usd = data["budget_usd"]
        if "daily_budget_usd" in data:
            k.daily_budget_usd = data["daily_budget_usd"]
        if "monthly_budget_usd" in data:
            k.monthly_budget_usd = data["monthly_budget_usd"]
        if "expires_at" in data:
            k.expires_at = _utc(data["expires_at"])
        if "allowed_models" in data:
            k.allowed_models = _clean_models(data["allowed_models"])
        s.flush()
        return key_out(k, s.get(User, k.user_id), ledger.key_spent(k.id))


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: int):
    with session_scope() as s:
        k = s.get(ApiKey, key_id)
        if k is None:
            raise ProxyError(404, "unknown key", code="not_found")
        k.revoked = True
    return {"revoked": key_id}
