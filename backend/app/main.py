from __future__ import annotations

import secrets
import os
import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from .adapters.registry import BUILTIN_PROVIDERS, DEFAULT_RAW_PROMPT
from . import metrics
from .api import admin, auth_ws
from .api import anthropic as anthropic_api
from .api import openai as openai_api
from .config import get_settings
from .db import init_engine, session_scope
from .errors import ProxyError
from .logging_setup import log, setup_logging
from .models import Provider
from .api.deps import require_admin
from .ratelimit import RateLimiter, RedisRateLimiter
from .runner.queue import LocalJobQueue, RedisJobQueue
from .service import ServiceState


def seed_providers() -> None:
    with session_scope() as s:
        for name, d in BUILTIN_PROVIDERS.items():
            if s.scalar(select(Provider).where(Provider.name == name)) is None:
                personal = os.environ.get("AGENTBRIDGE_SEED_PERSONAL") == "true"
                s.add(Provider(name=name, kind=name, enabled=personal, mode="raw",
                               auth_mode="oauth_cli" if personal else "api_key", use_host_home=personal,
                               raw_system_prompt=DEFAULT_RAW_PROMPT, extra={}, **d))  # fmt: skip


def load_admin_token() -> str:
    s = get_settings()
    if s.admin_token:
        return s.admin_token
    f = s.data_dir / "admin_token"
    if f.exists():
        return f.read_text().strip()
    tok = secrets.token_urlsafe(24)
    f.write_text(tok)
    f.chmod(0o600)
    log("admin_token.generated", path=str(f.resolve()))
    return tok


async def refresh_codex_models_periodically() -> None:
    from .codex_discovery import DiscoveryError, eligible, refresh_provider

    while True:
        with session_scope() as session:
            names = [p.name for p in session.scalars(select(Provider).where(Provider.kind == "codex")) if eligible(p)]
        for name in names:
            try:
                await refresh_provider(name)
            except DiscoveryError as exc:
                log("codex.model_discovery_failed", provider=name, error=str(exc))
            except Exception as exc:  # Keep background discovery from taking down the proxy.
                log("codex.model_discovery_failed", provider=name, error=type(exc).__name__)
        await asyncio.sleep(1800)


def create_app() -> FastAPI:
    setup_logging()
    s = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_engine()
        seed_providers()
        app.state.admin_token = load_admin_token()
        if s.queue_backend == "redis":
            if not s.redis_url:
                raise RuntimeError("PROXY_QUEUE_BACKEND=redis needs PROXY_REDIS_URL")
            app.state.limiter = RedisRateLimiter(s.redis_url, s.rate_limit_per_minute)
            queue = RedisJobQueue(s.redis_url, s.max_concurrency, s.per_user_concurrency, s.queue_timeout_s)
        elif s.queue_backend == "local":
            app.state.limiter = RateLimiter(s.rate_limit_per_minute)
            queue = LocalJobQueue(s.max_concurrency, s.per_user_concurrency, s.queue_timeout_s)
        else:
            raise RuntimeError(f"unknown PROXY_QUEUE_BACKEND {s.queue_backend!r} (use local or redis)")
        app.state.service = ServiceState(queue=queue)
        log("startup", host=s.host, port=s.port, db=s.db_url.split(":")[0], queue=s.queue_backend)
        discovery_task = asyncio.create_task(refresh_codex_models_periodically())
        try:
            yield
        finally:
            discovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await discovery_task

    app = FastAPI(title="AgentBridge", lifespan=lifespan, docs_url="/docs", redoc_url=None)

    @app.exception_handler(ProxyError)
    async def _proxy_error(_: Request, e: ProxyError):
        return JSONResponse(e.body(), status_code=e.status, headers=e.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        first = e.errors()[0]
        msg = f"Invalid request: {'.'.join(map(str, first['loc']))}: {first['msg']}"
        return JSONResponse(ProxyError(400, msg, "invalid_request_error", "invalid_request").body(), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        t = "invalid_request_error" if e.status_code < 500 else "server_error"
        return JSONResponse(ProxyError(e.status_code, str(e.detail), t, None).body(), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        log("unhandled_error", error=type(e).__name__)  # never echo internals / prompt contents to the client
        return JSONResponse(ProxyError(500, "Internal server error", "server_error", "internal_error").body(), status_code=500)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/metrics", include_in_schema=False)
    async def prometheus(request: Request):
        if not s.metrics_public:
            require_admin(request)
        q = request.app.state.service.queue.stats()
        return PlainTextResponse(metrics.render({"proxy_queue_running": q["running"], "proxy_queue_waiting": q["waiting"],
                                                 "proxy_queue_max_concurrency": q["max_concurrency"]}),
                                 media_type="text/plain; version=0.0.4")  # fmt: skip

    app.include_router(openai_api.router)
    app.include_router(anthropic_api.router)
    app.include_router(admin.router)
    app.include_router(auth_ws.router)

    dist = s.frontend_dist
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = (dist / path).resolve()
            if path and f.is_file() and f.is_relative_to(dist.resolve()):
                return FileResponse(f)
            # index.html must be revalidated, or browsers keep showing the previous build after an upgrade
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
