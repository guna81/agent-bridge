"""Anthropic Messages API compatibility: POST /v1/messages (+ /v1/messages/count_tokens).

Lets tools that speak the Anthropic API (the Anthropic SDKs, anything with a configurable Anthropic base URL)
use any enabled provider. Model ids are the proxy's own `provider/model`. Auth is the proxy key, sent either as
`x-api-key` (what the Anthropic SDK does) or as a Bearer token.

Errors use Anthropic's shape: {"type": "error", "error": {"type", "message"}}.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from .. import toolcall
from ..adapters.base import Done, Error, Image, NormalizedRequest, TextDelta, Usage
from ..errors import ProxyError
from ..pricing import estimate_tokens
from ..service import run_chat
from .common import check_image_count, check_key_limits, collect, decode_image, error_to_proxy, first_events, read_json_limited, resolve_routed_provider
from .deps import authenticate_key

router = APIRouter()


class MessagesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[dict]
    system: str | list[Any] | None = None
    max_tokens: int | None = None
    stream: bool = False
    temperature: float | None = None
    tools: list[Any] | None = None
    tool_choice: dict | None = None


_ERR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error", 404: "not_found_error",
              413: "request_too_large", 429: "rate_limit_error", 529: "overloaded_error"}  # fmt: skip


def _err_body(e: ProxyError) -> dict:
    return {"type": "error", "error": {"type": _ERR_TYPES.get(e.status, "api_error"), "message": e.message}}


def _err_response(e: ProxyError) -> JSONResponse:
    return JSONResponse(_err_body(e), status_code=e.status, headers=e.headers)


def _bad(msg: str, code: str = "invalid_request") -> ProxyError:
    return ProxyError(400, msg, "invalid_request_error", code)


def _system_text(system: str | list[Any] | None) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict) and b.get("type") == "text")


def _block_text(content: Any) -> str:
    """Text of a tool_result's content (string or list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return "" if content is None else json.dumps(content)


def parse_tools(body: MessagesRequest) -> tuple[list[toolcall.ToolSpec], str]:
    tc = body.tool_choice or {}
    if not body.tools or tc.get("type") == "none":
        return [], "auto"
    specs = []
    for t in body.tools:
        if not isinstance(t, dict) or not t.get("name") or "input_schema" not in t:
            raise _bad("Only client tools with `name` and `input_schema` are supported.", "unsupported_tool")
        specs.append(toolcall.ToolSpec(t["name"], t.get("description") or "", t.get("input_schema") or {}))
    choice = {"any": "required", "tool": tc.get("name") or "required"}.get(tc.get("type", "auto"), "auto")
    if choice not in ("auto", "required") and choice not in {s.name for s in specs}:
        raise _bad(f"tool_choice names an unknown tool {choice!r}.", "invalid_tool_choice")
    return specs, choice


def normalize(body: MessagesRequest, slug: str, tools: list[toolcall.ToolSpec], choice: str) -> NormalizedRequest:
    if not body.messages:
        raise _bad("`messages` must be a non-empty list.")
    turns: list[tuple[str, str]] = []
    images: list[Image] = []
    call_names: dict[str, str] = {}
    images_by_turn: dict[int, list[Image]] = {}
    for m in body.messages:
        before = len(images)
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant"):
            raise _bad(f"Unsupported message role {role!r}.")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        texts: list[str] = []
        results: list[str] = []
        for b in blocks:
            t = b.get("type") if isinstance(b, dict) else None
            if t == "text":
                texts.append(b.get("text", ""))
            elif t == "image":
                if role != "user":
                    raise _bad("Images are supported only in user messages.", "unsupported_content")
                src = b.get("source") or {}
                if src.get("type") != "base64":
                    raise _bad("Only base64 image sources are supported (remote image URLs are not fetched).", "unsupported_content")
                images.append(decode_image(src.get("media_type", ""), src.get("data", "")))
            elif t == "tool_use":
                call_names[str(b.get("id", ""))] = b.get("name", "")
                texts.append(toolcall.render_call(b.get("name", ""), b.get("input") or {}))
            elif t == "tool_result":
                cid = str(b.get("tool_use_id", ""))
                body_text = _block_text(b.get("content"))
                if b.get("is_error"):
                    body_text = "ERROR: " + body_text
                results.append(toolcall.render_result(cid, body_text, call_names.get(cid, "")))
            elif t in ("thinking", "redacted_thinking"):
                continue  # previous reasoning is not replayed to the CLI
            else:
                raise _bad(f"Unsupported content block type {t!r}.", "unsupported_content")
        if results:
            turns.append(("tool", "\n".join(results)))
        text = "\n".join(x for x in texts if x)
        if text or not results or len(images) != before:
            if len(images) != before:
                images_by_turn[len(turns)] = images[before:]
            turns.append((role, text))
    check_image_count(images)
    system = [_system_text(body.system)]
    if tools:
        system.append(toolcall.instructions(tools, choice))
    return NormalizedRequest(model=slug, system="\n\n".join(s for s in system if s), turns=turns, stream=body.stream,
                             max_tokens=body.max_tokens, temperature=body.temperature, images=images, images_by_turn=images_by_turn)  # fmt: skip


def _usage(usage: Usage | None) -> dict:
    return {"input_tokens": usage.input_tokens if usage else 0, "output_tokens": usage.output_tokens if usage else 0}


def _stop_reason(finish: str, calls: list) -> str:
    return "tool_use" if calls else ("max_tokens" if finish == "length" else "end_turn")


def _content_blocks(text: str, calls: list[toolcall.ToolCall]) -> list[dict]:
    blocks: list[dict] = [{"type": "text", "text": text}] if text or not calls else []
    blocks += [{"type": "tool_use", "id": "toolu_" + c.id.removeprefix("call_"), "name": c.name, "input": c.arguments} for c in calls]
    return blocks


@router.post("/v1/messages")
async def messages(request: Request):
    try:
        key, user = authenticate_key(request)
        try:
            body = MessagesRequest.model_validate(await read_json_limited(request))
        except ValidationError as e:
            first = e.errors()[0]
            raise _bad(f"Invalid request: {'.'.join(map(str, first['loc']))}: {first['msg']}") from None
        requested_model = body.model
        provider, slug, body.model = resolve_routed_provider(key, requested_model)
        budget_cap = check_key_limits(key, body.model)
        tools, choice = parse_tools(body)
        nreq = normalize(body, slug, tools, choice)
        msg_id = "msg_" + uuid.uuid4().hex[:24]
        headers = {"X-Request-Id": msg_id, "X-Proxy-Model": body.model}
        if body.model != requested_model:
            headers["X-Proxy-Requested-Model"] = requested_model
        gen = run_chat(request.app.state.service, provider, user.id, nreq, msg_id, key_id=key.id, budget_cap=budget_cap)
        sse_headers = {**headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

        if tools or not body.stream:
            text, usage, finish = await collect(request, gen)
            calls: list[toolcall.ToolCall] = []
            if tools:
                text, calls = toolcall.parse(text, tools)
            blocks, stop = _content_blocks(text, calls), _stop_reason(finish, calls)
            if body.stream:  # tool replies are parsed whole, then replayed as a stream
                return StreamingResponse(_sse_buffered(msg_id, body.model, blocks, stop, usage), media_type="text/event-stream", headers=sse_headers)
            return JSONResponse({"id": msg_id, "type": "message", "role": "assistant", "model": body.model, "content": blocks,
                                 "stop_reason": stop, "stop_sequence": None, "usage": _usage(usage)}, headers=headers)  # fmt: skip

        first = await first_events(gen)
        return StreamingResponse(_sse(gen, first, msg_id, body.model), media_type="text/event-stream", headers=sse_headers)
    except ProxyError as e:
        return _err_response(e)


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    """Rough estimate (~4 characters per token); the CLIs expose no tokenizer."""
    try:
        authenticate_key(request)
        body = await read_json_limited(request)
        parts = [_system_text(body.get("system"))]
        for m in body.get("messages") or []:
            c = m.get("content") if isinstance(m, dict) else None
            parts.append(c if isinstance(c, str) else json.dumps(c or ""))
        if body.get("tools"):
            parts.append(json.dumps(body["tools"]))
        return {"input_tokens": estimate_tokens("\n".join(parts))}
    except ProxyError as e:
        return _err_response(e)


def _ev(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps({'type': name, **data})}\n\n"


def _start(msg_id: str, model: str) -> str:
    return _ev("message_start", {"message": {"id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
                                             "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})  # fmt: skip


def _end(stop: str, usage: Usage | None) -> str:
    return (_ev("message_delta", {"delta": {"stop_reason": stop, "stop_sequence": None}, "usage": _usage(usage)})
            + _ev("message_stop", {}))  # fmt: skip


async def _sse_buffered(msg_id: str, model: str, blocks: list[dict], stop: str, usage: Usage | None) -> AsyncIterator[str]:
    yield _start(msg_id, model)
    for i, b in enumerate(blocks):
        if b["type"] == "text":
            yield _ev("content_block_start", {"index": i, "content_block": {"type": "text", "text": ""}})
            yield _ev("content_block_delta", {"index": i, "delta": {"type": "text_delta", "text": b["text"]}})
        else:
            yield _ev("content_block_start", {"index": i, "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
            yield _ev("content_block_delta", {"index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}})
        yield _ev("content_block_stop", {"index": i})
    yield _end(stop, usage)


async def _sse(gen, first: list, msg_id: str, model: str) -> AsyncIterator[str]:  # noqa: ANN001
    usage: Usage | None = None
    stop = "end_turn"
    try:
        yield _start(msg_id, model)
        yield _ev("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}})

        async def events():
            for ev in first:
                yield ev
            async for ev in gen:
                yield ev

        async for ev in events():
            if isinstance(ev, TextDelta):
                yield _ev("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": ev.text}})
            elif isinstance(ev, Usage):
                usage = ev
            elif isinstance(ev, Done):
                stop = "max_tokens" if ev.finish_reason == "length" else "end_turn"
            elif isinstance(ev, Error):
                yield _ev("error", {"error": _err_body(error_to_proxy(ev))["error"]})
                return
        yield _ev("content_block_stop", {"index": 0})
        yield _end(stop, usage)
    finally:
        await gen.aclose()  # client disconnect lands here: closing the generator kills the process group
