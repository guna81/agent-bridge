from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from .. import ledger, toolcall
from ..adapters.base import Done, Error, Image, NormalizedRequest, TextDelta, Usage
from ..db import session_scope
from ..errors import ProxyError
from ..models import Provider
from ..service import run_chat
from .common import (
    check_image_count,
    check_key_limits,
    collect,
    error_to_proxy,
    first_events,
    image_from_url,
    model_allowed,
    read_json_limited,
    resolve_provider,
)
from .deps import authenticate_key

router = APIRouter()


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: str | list[Any] | None = None
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    n: int | None = 1
    stream_options: dict | None = None
    tools: list[Any] | None = None
    tool_choice: Any = None


def _parts_of(m: ChatMessage, images: list[Image]) -> str:
    """Text of a message; image parts are appended to `images`."""
    c = m.content
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    parts = []
    for p in c:
        t = p.get("type") if isinstance(p, dict) else None
        if t in ("text", "input_text"):
            parts.append(p.get("text", ""))
        elif t == "image_url":
            iu = p.get("image_url")
            images.append(image_from_url(iu.get("url", "") if isinstance(iu, dict) else str(iu or "")))
        else:
            raise ProxyError(400, "Only text and image_url content parts are supported.", "invalid_request_error", "unsupported_content")
    return "\n".join(parts)


def parse_tools(body: ChatRequest) -> tuple[list[toolcall.ToolSpec], str]:
    """-> (tool specs, choice). No tools, or tool_choice "none", gives ([], "auto")."""
    tc = body.tool_choice
    if not body.tools or tc == "none":
        return [], "auto"
    specs = []
    for t in body.tools:
        f = t.get("function") if isinstance(t, dict) else None
        if not isinstance(f, dict) or not f.get("name"):
            raise ProxyError(400, "Only tools of type `function` with a name are supported.", "invalid_request_error", "unsupported_tool")
        specs.append(toolcall.ToolSpec(f["name"], f.get("description") or "", f.get("parameters") or {}))
    choice = "auto"
    if tc == "required":
        choice = "required"
    elif isinstance(tc, dict):
        choice = (tc.get("function") or {}).get("name") or "required"
        if choice != "required" and choice not in {s.name for s in specs}:
            raise ProxyError(400, f"tool_choice names an unknown function {choice!r}.", "invalid_request_error", "invalid_tool_choice")
    return specs, choice


def normalize(body: ChatRequest, slug: str, tools: list[toolcall.ToolSpec] | None = None, choice: str = "auto") -> NormalizedRequest:
    if not body.messages:
        raise ProxyError(400, "`messages` must be a non-empty list.")
    if (body.n or 1) != 1:
        raise ProxyError(400, "Only n=1 is supported.", "invalid_request_error", "unsupported_parameter")
    system: list[str] = []
    turns: list[tuple[str, str]] = []
    images: list[Image] = []
    call_names: dict[str, str] = {}
    for m in body.messages:
        text = _parts_of(m, images)
        if m.role in ("system", "developer"):
            system.append(text)
        elif m.role == "user":
            turns.append(("user", text))
        elif m.role == "assistant":
            calls = []
            for c in m.tool_calls or []:
                f = (c.get("function") or {}) if isinstance(c, dict) else {}
                if f.get("name"):
                    call_names[str(c.get("id", ""))] = f["name"]
                    calls.append(toolcall.render_call(f["name"], f.get("arguments") or "{}"))
            turns.append(("assistant", "\n".join(x for x in (text, *calls) if x)))
        elif m.role in ("tool", "function"):
            cid = m.tool_call_id or ""
            turns.append(("tool", toolcall.render_result(cid, text, call_names.get(cid) or m.name or "")))
        else:
            raise ProxyError(400, f"Unsupported message role {m.role!r}.")
    if not turns:
        raise ProxyError(400, "At least one non-system message is required.")
    check_image_count(images)
    if tools:
        system.append(toolcall.instructions(tools, choice))
    return NormalizedRequest(model=slug, system="\n\n".join(s for s in system if s), turns=turns, stream=body.stream,
                             max_tokens=body.max_completion_tokens or body.max_tokens, temperature=body.temperature,
                             images=images)  # fmt: skip


def ignored_params(body: ChatRequest, provider: Provider) -> list[str]:
    if provider.backend == "direct":
        return []
    ig = []
    if body.temperature is not None:
        ig.append("temperature")
    if (body.max_tokens or body.max_completion_tokens) is not None:
        ig.append("max_tokens")
    return ig


@router.get("/v1/models")
async def list_models(request: Request):
    key, _ = authenticate_key(request)
    now = int(time.time())
    with session_scope() as s:
        data = [
            {"id": f"{p.name}/{m}", "object": "model", "created": now, "owned_by": p.name}
            for p in s.scalars(select(Provider).where(Provider.enabled.is_(True)).order_by(Provider.name))
            for m in dict.fromkeys([*(p.models or []), *([p.default_model] if p.default_model else [])])
        ]
    return {"object": "list", "data": [d for d in data if model_allowed(key, d["id"])]}


@router.get("/v1/me")
async def me(request: Request):
    key, user = authenticate_key(request)
    out = {"user": user.name, "key_prefix": key.prefix, **ledger.usage_summary(user.id)}
    if key.budget_usd is not None:
        spent = ledger.key_spent(key.id)
        out["key_budget_usd"] = key.budget_usd
        out["key_spent_usd"] = spent
        out["key_remaining_usd"] = max(0.0, key.budget_usd - spent)
    return out


def _usage(usage: Usage | None) -> dict:
    pt, ct = (usage.input_tokens, usage.output_tokens) if usage else (0, 0)
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}


def _openai_calls(calls: list[toolcall.ToolCall], *, with_index: bool = False) -> list[dict]:
    return [
        {**({"index": i} if with_index else {}), "id": c.id, "type": "function",
         "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
        for i, c in enumerate(calls)
    ]  # fmt: skip


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    key, user = authenticate_key(request)
    try:
        body = ChatRequest.model_validate(await read_json_limited(request))
    except ValidationError as e:
        first = e.errors()[0]
        raise ProxyError(400, f"Invalid request: {'.'.join(map(str, first['loc']))}: {first['msg']}", "invalid_request_error", "invalid_request") from None
    provider, slug = resolve_provider(body.model)
    budget_cap = check_key_limits(key, body.model)
    tools, choice = parse_tools(body)
    nreq = normalize(body, slug, tools, choice)
    request_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())
    headers = {"X-Request-Id": request_id}
    ig = ignored_params(body, provider)
    if ig:
        headers["X-Proxy-Ignored-Params"] = ",".join(ig)
    gen = run_chat(request.app.state.service, provider, user.id, nreq, request_id, key_id=key.id, budget_cap=budget_cap)
    include_usage = bool((body.stream_options or {}).get("include_usage"))
    sse_headers = {**headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    if tools:
        # Tool replies are parsed as a whole, so they are buffered even when stream=true.
        text, usage, finish = await collect(request, gen)
        content, calls = toolcall.parse(text, tools)
        if calls:
            finish = "tool_calls"
        if body.stream:
            return StreamingResponse(_sse_buffered(request_id, created, body.model, content, calls, finish, usage, include_usage),
                                     media_type="text/event-stream", headers=sse_headers)  # fmt: skip
        msg: dict = {"role": "assistant", "content": content or None if calls else content}
        if calls:
            msg["tool_calls"] = _openai_calls(calls)
        return JSONResponse({
            "id": request_id, "object": "chat.completion", "created": created, "model": body.model,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}], "usage": _usage(usage),
        }, headers=headers)  # fmt: skip

    if not body.stream:
        text, usage, finish = await collect(request, gen)
        return JSONResponse({
            "id": request_id, "object": "chat.completion", "created": created, "model": body.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": _usage(usage),
        }, headers=headers)  # fmt: skip

    # Streaming: pull the first event before committing to a 200 so early failures are proper HTTP errors.
    first = await first_events(gen)
    return StreamingResponse(_sse(gen, first, request_id, created, body.model, include_usage), media_type="text/event-stream",
                             headers=sse_headers)  # fmt: skip


def _chunk(rid: str, created: int, model: str, delta: dict, finish: str | None) -> str:
    return "data: " + json.dumps({
        "id": rid, "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }) + "\n\n"  # fmt: skip


def _usage_chunk(rid: str, created: int, model: str, usage: Usage) -> str:
    return "data: " + json.dumps({"id": rid, "object": "chat.completion.chunk", "created": created, "model": model,
                                  "choices": [], "usage": _usage(usage)}) + "\n\n"  # fmt: skip


async def _sse_buffered(rid: str, created: int, model: str, content: str, calls: list[toolcall.ToolCall], finish: str,
                        usage: Usage | None, include_usage: bool) -> AsyncIterator[str]:  # fmt: skip
    yield _chunk(rid, created, model, {"role": "assistant", "content": ""}, None)
    if content:
        yield _chunk(rid, created, model, {"content": content}, None)
    if calls:
        yield _chunk(rid, created, model, {"tool_calls": _openai_calls(calls, with_index=True)}, None)
    yield _chunk(rid, created, model, {}, finish)
    if include_usage and usage is not None:
        yield _usage_chunk(rid, created, model, usage)
    yield "data: [DONE]\n\n"


async def _sse(gen, first: list, rid: str, created: int, model: str, include_usage: bool) -> AsyncIterator[str]:  # noqa: ANN001
    usage: Usage | None = None
    finished = False
    try:
        yield _chunk(rid, created, model, {"role": "assistant", "content": ""}, None)

        async def events():
            for ev in first:
                yield ev
            async for ev in gen:
                yield ev

        async for ev in events():
            if isinstance(ev, TextDelta):
                yield _chunk(rid, created, model, {"content": ev.text}, None)
            elif isinstance(ev, Usage):
                usage = ev
            elif isinstance(ev, Done):
                yield _chunk(rid, created, model, {}, ev.finish_reason)
                finished = True
            elif isinstance(ev, Error):
                err = error_to_proxy(ev).body()
                yield f"data: {json.dumps(err)}\n\n"
                finished = True
                break
        if not finished:
            yield _chunk(rid, created, model, {}, "stop")
        if include_usage and usage is not None:
            yield _usage_chunk(rid, created, model, usage)
        yield "data: [DONE]\n\n"
    finally:
        # client disconnect / cancellation lands here: closing the generator kills the process group
        await gen.aclose()
