"""Runs one chat request end to end: admission -> workdir -> adapter -> subprocess -> events -> ledger."""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import AsyncIterator

import httpx

from . import ledger, metrics
from .adapters.base import Done, Error, Event, NormalizedRequest, RunContext, TextDelta, ToolEvent, Usage
from .adapters.registry import new_adapter
from .backends.direct import stream_direct
from .config import get_settings
from .errors import ProxyError
from .logging_setup import log
from .models import Provider
from .pricing import estimate_cost, estimate_tokens
from .runner.env import build_env, host_home
from .runner.process import RunResult, RunTimeout, stream_lines
from .runner.queue import JobQueue, QueueTimeout
from .runner.workdir import fresh_workdir, user_home
from .security import decrypt_secret


@dataclass
class ServiceState:
    queue: JobQueue
    direct_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport


async def run_chat(
    state: ServiceState, provider: Provider, user_id: int | None, req: NormalizedRequest, request_id: str,
    *, raw_sink: list[str] | None = None, key_id: int | None = None, budget_cap: float | None = None,
) -> AsyncIterator[Event]:  # fmt: skip
    """Yield TextDelta / Usage / Done / Error. ToolEvents never leave this function.

    user_id=None means an unbilled admin test run (still written to the ledger, with no user).
    budget_cap is what is left of the API key's own budget, if it has one.
    """
    s = get_settings()
    if provider.backend == "cli" and provider.auth_mode == "oauth_cli" and not s.single_user_personal_use:
        raise ProxyError(403, "oauth_cli auth mode is disabled: set PROXY_SINGLE_USER_PERSONAL_USE=true for personal single-user "
                              "deployments, or switch this provider to api_key mode.", "permission_error", "oauth_disabled")  # fmt: skip
    if len(req.prompt.encode()) > s.max_prompt_bytes:
        raise ProxyError(413, f"Prompt exceeds {s.max_prompt_bytes} bytes", "invalid_request_error", "context_length_exceeded")
    if req.images and not _supports_images(provider):
        raise ProxyError(400, f"Provider `{provider.name}` does not accept image input"
                              + (" through its CLI; switch it to the direct API backend." if provider.kind in DIRECT_KINDS else "."),
                         "invalid_request_error", "unsupported_content")  # fmt: skip

    budget = provider.max_budget_usd or s.default_max_budget_usd
    if user_id is not None:
        bal = ledger.balance(user_id)
        if bal <= 0:
            raise ProxyError(429, "You have no remaining credits.", "insufficient_quota", "insufficient_quota")
        budget = max(0.001, min(budget, bal))
    if budget_cap is not None:
        budget = max(0.001, min(budget, budget_cap))

    api_key = decrypt_secret(provider.api_key_enc) if provider.api_key_enc else None
    model_label = f"{provider.name}/{req.model}"
    t0 = time.monotonic()
    text_parts: list[str] = []
    usage: Usage | None = None
    status = "aborted"
    try:
        try:
            async with state.queue.slot(user_id or 0):
                events = (
                    stream_direct(provider.kind, req, api_key=api_key or "", system_default=provider.raw_system_prompt,
                                  extra=provider.extra or {}, timeout=s.request_timeout_s, transport=state.direct_transport)
                    if provider.backend == "direct"
                    else _cli_events(provider, user_id or 0, req, api_key, budget, raw_sink)
                )  # fmt: skip
                try:
                    async for ev in events:
                        if isinstance(ev, ToolEvent):
                            continue
                        if isinstance(ev, TextDelta):
                            text_parts.append(ev.text)
                        elif isinstance(ev, Usage):
                            usage = ev
                        elif isinstance(ev, Error):
                            status = "error"
                            yield ev
                            return
                        if isinstance(ev, Done):
                            status = "ok"
                        yield ev
                finally:
                    await events.aclose()
        except QueueTimeout as e:
            raise ProxyError(503, str(e), "server_error", "server_busy", {"Retry-After": "5"}) from None
    finally:
        text = "".join(text_parts)
        if usage and (usage.input_tokens or usage.output_tokens):
            in_tok, out_tok = usage.input_tokens, usage.output_tokens
            cost = usage.cost_usd if usage.cost_usd is not None else estimate_cost(req.model, in_tok, out_tok)
            estimated = usage.cost_usd is None
        else:
            in_tok, out_tok = estimate_tokens(req.system + req.prompt), estimate_tokens(text)
            cost = estimate_cost(req.model, in_tok, out_tok) if (text and status != "error") else 0.0
            estimated = True
        ledger.record(user_id=user_id, key_id=key_id, request_id=request_id, provider=provider.name, model=req.model,
                      input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost, estimated=estimated, status=status)  # fmt: skip
        metrics.observe_request(provider.name, req.model, status, in_tok, out_tok, cost, time.monotonic() - t0)
        log("chat.finished", request_id=request_id, user_id=user_id, model=model_label, status=status,
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=round(cost, 6), estimated=estimated,
            duration_ms=int((time.monotonic() - t0) * 1000),
            **({"prompt": req.prompt[:2000]} if s.debug_log_prompts else {}))  # fmt: skip


DIRECT_KINDS = ("claude", "agy", "gemini")  # kinds stream_direct can serve


def _supports_images(provider: Provider) -> bool:
    if provider.backend == "direct":
        return provider.kind in DIRECT_KINDS
    try:
        return new_adapter(provider.kind).supports_images
    except ValueError:
        return False


async def _cli_events(provider: Provider, user_id: int, req: NormalizedRequest, api_key: str | None, budget: float,
                      raw_sink: list[str] | None) -> AsyncIterator[Event]:  # fmt: skip
    s = get_settings()
    adapter = new_adapter(provider.kind)
    with fresh_workdir() as tmp:
        home = host_home() if provider.use_host_home else str(user_home(provider.name, user_id))
        from pathlib import Path

        # Agent mode may be pinned to a real project directory (provider.extra["workdir"]) so an agent can work on
        # a codebase across requests. Raw mode always gets the throwaway temp dir.
        project = (provider.extra or {}).get("workdir") if provider.mode == "agent" else None
        if project and not Path(project).is_dir():
            yield Error(f"configured workdir {project!r} does not exist", "bad_workdir")
            return
        wd = Path(project) if project else tmp
        if project and req.system and provider.kind != "claude":
            # these CLIs take the system prompt as a file in the workdir; never write that into a real project
            first_role, first_text = req.turns[0]
            req = replace(req, system="", turns=[(first_role, f"Instructions:\n{req.system}\n\n{first_text}"), *req.turns[1:]])
        ctx = RunContext(
            scratch=tmp if project else None,
            provider_name=provider.name, mode=provider.mode, auth_mode=provider.auth_mode,  # type: ignore[arg-type]
            workdir=wd, home=Path(home), binary=provider.binary_path or provider.kind,
            raw_system_prompt=provider.raw_system_prompt, api_key=api_key,
            skip_permissions=provider.skip_permissions and provider.mode == "agent",  # never in raw mode
            use_host_home=provider.use_host_home, max_budget_usd=budget, extra=dict(provider.extra or {}),
        )  # fmt: skip
        if not project:
            adapter.prepare_workdir(req, ctx)
        cmd = adapter.build_command(req, ctx)
        env = build_env(ctx, cmd.env, pty=cmd.use_pty)
        result = RunResult()
        saw_done = False
        try:
            async for line in stream_lines(cmd, env, s.request_timeout_s, result):
                if raw_sink is not None and len(raw_sink) < 300:
                    raw_sink.append(line[:4000])
                for ev in adapter.parse_line(line):
                    saw_done |= isinstance(ev, Done)
                    yield ev
                    if isinstance(ev, Error):
                        return
            for ev in adapter.finish():
                saw_done |= isinstance(ev, Done)
                yield ev
                if isinstance(ev, Error):
                    return
        except RunTimeout as e:
            yield Error(str(e), "timeout")
            return
        except FileNotFoundError:
            yield Error(f"CLI binary {cmd.argv[0]!r} not found", "cli_not_installed")
            return
        except PermissionError:
            yield Error(f"CLI binary {cmd.argv[0]!r} is not executable", "cli_not_installed")
            return
        rc = result.returncode
        if rc not in (0, None) and not saw_done:
            tail = result.stderr_tail.strip()[-400:]
            yield Error(f"CLI exited with status {rc}" + (f": {tail}" if tail else ""), "cli_error")
        elif not saw_done:
            yield Done()
