from __future__ import annotations

import datetime as dt

from fastapi import Request
from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..errors import ProxyError, unauthorized
from ..models import ApiKey, User
from ..security import constant_time_eq, hash_proxy_key


def bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def _expired(key: ApiKey) -> bool:
    if key.expires_at is None:
        return False
    exp = key.expires_at if key.expires_at.tzinfo else key.expires_at.replace(tzinfo=dt.timezone.utc)
    return exp <= dt.datetime.now(dt.timezone.utc)


def authenticate_key(request: Request) -> tuple[ApiKey, User]:
    token = bearer(request) or request.headers.get("x-api-key")  # x-api-key: Anthropic SDK style
    if not token:
        raise unauthorized("Missing API key. Send 'Authorization: Bearer <proxy-key>' (or 'x-api-key').")
    with session_scope() as s:
        key = s.scalar(select(ApiKey).where(ApiKey.key_hash == hash_proxy_key(token)))
        if key is None or key.revoked:
            raise unauthorized()
        if _expired(key):
            raise unauthorized("This API key has expired.")
        user = s.get(User, key.user_id)
        key.last_used_at = dt.datetime.now(dt.timezone.utc)
        s.flush()
        s.expunge_all()
    request.app.state.limiter.check(key.id)
    return key, user


def require_admin(request: Request) -> None:
    token = bearer(request) or request.headers.get("x-admin-token")
    expected = request.app.state.admin_token
    if not expected or not token or not constant_time_eq(token, expected):
        raise ProxyError(401, "Admin token required", "authentication_error", "invalid_admin_token")
