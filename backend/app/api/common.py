"""Shared request plumbing for the OpenAI- and Anthropic-compatible endpoints."""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import fnmatch
import json
import re

from fastapi import Request
from sqlalchemy import select

from .. import ledger, metrics
from ..adapters.base import Done, Error, Image, TextDelta, Usage
from ..adapters.base import resolve_binary
from ..config import get_settings
from ..db import session_scope
from ..errors import ProxyError, not_found_model
from ..models import ApiKey, Provider
from ..provider_models import provider_models

_DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|gif|webp));base64,(.*)$", re.DOTALL)
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


async def read_json_limited(request: Request) -> dict:
    limit = get_settings().max_body_bytes
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > limit:
        raise ProxyError(413, f"Request body exceeds {limit} bytes.", "invalid_request_error", "request_too_large")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise ProxyError(413, f"Request body exceeds {limit} bytes.", "invalid_request_error", "request_too_large")
    try:
        return json.loads(bytes(buf) or b"{}")
    except json.JSONDecodeError:
        raise ProxyError(400, "Request body is not valid JSON.", "invalid_request_error", "invalid_json") from None


def resolve_provider(model: str) -> tuple[Provider, str]:
    if "/" not in model:
        raise ProxyError(400, "Model must be of the form `provider/model`, see GET /v1/models.", "invalid_request_error", "model_not_found")
    pname, slug = model.split("/", 1)
    with session_scope() as s:
        p = s.scalar(select(Provider).where(Provider.name == pname, Provider.enabled.is_(True)))
        if p is None:
            raise not_found_model(model)
        s.expunge(p)
    if slug not in provider_models(p):
        raise not_found_model(model)
    return p, slug


def model_allowed(key: ApiKey, model: str) -> bool:
    """allowed_models is a list of exact ids or glob patterns (`claude/*`). Empty/None = everything."""
    pats = key.allowed_models or []
    return not pats or any(fnmatch.fnmatchcase(model, p) for p in pats)


def resolve_routed_provider(key: ApiKey, model: str) -> tuple[Provider, str, str]:
    """Use an explicit fallback only when the primary is unavailable before execution.

    Never retry after a subprocess or upstream request has started, since it may
    have incurred a charge. Both the requested and selected models must be allowed.
    """
    if not model_allowed(key, model):
        raise ProxyError(403, f"This API key is not allowed to use the model `{model}`.", "permission_error", "model_not_allowed")
    if "/" not in model:
        raise not_found_model(model)
    name, slug = model.split("/", 1)
    with session_scope() as s:
        primary = s.scalar(select(Provider).where(Provider.name == name))
        if primary is None or slug not in provider_models(primary):
            raise not_found_model(model)
        s.expunge(primary)
    unavailable = not primary.enabled or (primary.backend == "cli" and not resolve_binary(primary.binary_path or primary.kind)) or (
        primary.backend == "direct" and not primary.api_key_enc)
    fallback = (primary.extra or {}).get("fallback_model")
    if unavailable and isinstance(fallback, str) and fallback and fallback != model:
        if not model_allowed(key, fallback):
            raise ProxyError(403, f"This API key is not allowed to use the fallback model `{fallback}`.", "permission_error", "model_not_allowed")
        selected, selected_slug = resolve_provider(fallback)
        return selected, selected_slug, fallback
    selected, selected_slug = resolve_provider(model)
    return selected, selected_slug, model


def check_key_limits(key: ApiKey, model: str) -> float | None:
    """Enforce the key's model allow-list and budget. Returns what is left of the budget (None = no cap)."""
    if not model_allowed(key, model):
        metrics.inc("proxy_http_rejections_total", reason="model_not_allowed")
        raise ProxyError(403, f"This API key is not allowed to use the model `{model}`.", "permission_error", "model_not_allowed")
    if key.budget_usd is None:
        return None
    left = key.budget_usd - ledger.key_spent(key.id)
    if left <= 0:
        metrics.inc("proxy_http_rejections_total", reason="key_budget_exhausted")
        raise ProxyError(429, "This API key has used up its budget.", "insufficient_quota", "key_budget_exhausted")
    return left


def decode_image(media_type: str, b64: str) -> Image:
    s = get_settings()
    if media_type not in IMAGE_TYPES:
        raise ProxyError(400, f"Unsupported image type {media_type!r}; use PNG, JPEG, GIF or WebP.", "invalid_request_error", "unsupported_content")
    try:
        data = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        raise ProxyError(400, "Image data is not valid base64.", "invalid_request_error", "invalid_image") from None
    if not data:
        raise ProxyError(400, "Image data is empty.", "invalid_request_error", "invalid_image")
    if len(data) > s.max_image_bytes:
        raise ProxyError(413, f"Image exceeds {s.max_image_bytes} bytes.", "invalid_request_error", "image_too_large")
    return Image(media_type, data)


def image_from_url(url: str) -> Image:
    """OpenAI `image_url`. Only inline data: URLs are accepted; the proxy never fetches remote URLs."""
    m = _DATA_URL.match(url or "")
    if not m:
        raise ProxyError(400, "Only base64 `data:` image URLs are supported (remote image URLs are not fetched).",
                         "invalid_request_error", "unsupported_content")  # fmt: skip
    return decode_image(m.group(1), m.group(2))


def check_image_count(images: list[Image]) -> None:
    n = get_settings().max_images
    if len(images) > n:
        raise ProxyError(400, f"At most {n} images per request.", "invalid_request_error", "too_many_images")


def error_to_proxy(e: Error) -> ProxyError:
    status = {"timeout": 504, "budget_exceeded": 402, "cli_not_installed": 503, "auth_error": 401}.get(e.code, 502)
    return ProxyError(status, e.message, "server_error" if status >= 500 else "invalid_request_error", e.code)


async def first_events(gen) -> list:  # noqa: ANN001
    """Pull events until the first one that carries content (text/done), buffering Usage.

    Lets us still answer with a proper HTTP error status if the CLI fails before producing anything.
    """
    buffered: list = []
    try:
        async for ev in gen:
            if isinstance(ev, Error):
                raise error_to_proxy(ev)
            buffered.append(ev)
            if not isinstance(ev, Usage):
                break
    except BaseException:
        await gen.aclose()
        raise
    return buffered


async def collect(request: Request, gen) -> tuple[str, Usage | None, str]:  # noqa: ANN001
    """Drain a run to (text, usage, finish_reason); kills the CLI if the client disconnects."""
    parts: list[str] = []
    usage: Usage | None = None
    finish = "stop"

    async def pump():
        nonlocal usage, finish
        try:
            async for ev in gen:
                if isinstance(ev, TextDelta):
                    parts.append(ev.text)
                elif isinstance(ev, Usage):
                    usage = ev
                elif isinstance(ev, Done):
                    finish = ev.finish_reason
                elif isinstance(ev, Error):
                    raise error_to_proxy(ev)
        finally:
            await gen.aclose()

    task = asyncio.create_task(pump())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.5)
            if done:
                break
            if await request.is_disconnected():
                task.cancel()  # run_chat's finally kills the CLI's process group
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise ProxyError(499, "Client closed request", "invalid_request_error", "client_closed_request")
        await task  # re-raises ProxyError from pump()
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    return "".join(parts), usage, finish
