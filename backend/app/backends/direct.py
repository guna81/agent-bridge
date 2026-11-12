"""Optional "direct API" backend: bypasses the CLI entirely. The only truly raw path.

provider.extra keys (all optional):
  base_url           override API host (tests / gateways)
  direct_model_map   {slug: api model id}
"""
from __future__ import annotations

import base64
import json
from typing import AsyncIterator

import httpx

from ..adapters.base import Done, Error, Event, NormalizedRequest, TextDelta, Usage
from ..adapters.claude import DEFAULT_RAW_PROMPT

ANTHROPIC_MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}


def _merge_turns(req: NormalizedRequest, assistant_role: str) -> list[dict]:
    """Merge neighbouring roles while retaining each turn's image associations."""
    out: list[dict] = []
    images_by_turn = req.images_by_turn
    if req.images and not images_by_turn:
        last_user = next((i for i in range(len(req.turns) - 1, -1, -1) if req.turns[i][0] == "user"), -1)
        images_by_turn = {last_user: req.images}
    for index, (role, text) in enumerate(req.turns):
        r = assistant_role if role == "assistant" else "user"
        parts = [("image", image) for image in images_by_turn.get(index, [])] + [("text", text)]
        if out and out[-1]["_r"] == r:
            out[-1]["_parts"].extend(parts)
        else:
            out.append({"_r": r, "_parts": parts})
    return out


def _anthropic_content(parts: list[tuple[str, object]]) -> str | list[dict]:
    if all(kind == "text" for kind, _ in parts):
        return "\n\n".join(str(value) for _, value in parts)
    return [
        ({"type": "text", "text": value} if kind == "text" else
         {"type": "image", "source": {"type": "base64", "media_type": value.media_type,
                                        "data": base64.b64encode(value.data).decode()}})
        for kind, value in parts if kind != "text" or value
    ]


async def stream_direct(kind: str, req: NormalizedRequest, *, api_key: str, system_default: str, extra: dict,
                        timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> AsyncIterator[Event]:  # fmt: skip
    if not api_key:
        yield Error("no API key configured for direct backend", "auth_error")
        return
    system = "\n\n".join(s for s in (system_default or DEFAULT_RAW_PROMPT, req.system) if s)
    mm = extra.get("direct_model_map", {})
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        if kind == "claude":
            gen = _anthropic(client, req, api_key, system, extra, mm)
        elif kind in ("agy", "gemini"):
            gen = _gemini(client, req, api_key, system, extra, mm)
        else:
            yield Error(f"direct backend not available for provider kind {kind!r}", "unsupported")
            return
        async for ev in gen:
            yield ev


async def _anthropic(client, req, api_key, system, extra, mm):  # noqa: ANN001
    base = extra.get("base_url", "https://api.anthropic.com")
    body = {
        "model": mm.get(req.model) or ANTHROPIC_MODELS.get(req.model, req.model),
        "max_tokens": req.max_tokens or 4096,
        "stream": True,
        "system": system,
        "messages": [{"role": m["_r"], "content": _anthropic_content(m["_parts"])}
                     for m in _merge_turns(req, "assistant")],
    }
    if req.temperature is not None:
        body["temperature"] = req.temperature
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    in_tok = out_tok = 0
    stop = "stop"
    async with client.stream("POST", f"{base}/v1/messages", json=body, headers=headers) as r:
        if r.status_code >= 400:
            yield Error(_err_text(await r.aread(), r.status_code), f"upstream_{r.status_code}")
            return
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "message_start":
                u = d["message"].get("usage", {})
                in_tok = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
            elif t == "content_block_delta" and d["delta"].get("type") == "text_delta":
                yield TextDelta(d["delta"]["text"])
            elif t == "message_delta":
                out_tok = d.get("usage", {}).get("output_tokens", out_tok)
                if d.get("delta", {}).get("stop_reason") == "max_tokens":
                    stop = "length"
            elif t == "error":
                yield Error(d.get("error", {}).get("message", "upstream error"), "upstream_error")
                return
    yield Usage(in_tok, out_tok, None)
    yield Done(stop)  # type: ignore[arg-type]


async def _gemini(client, req, api_key, system, extra, mm):  # noqa: ANN001
    base = extra.get("base_url", "https://generativelanguage.googleapis.com")
    model = mm.get(req.model) or req.model.removesuffix("-high").removesuffix("-medium").removesuffix("-low")
    body: dict = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": m["_r"], "parts": [
            ({"text": value} if kind == "text" else
             {"inlineData": {"mimeType": value.media_type, "data": base64.b64encode(value.data).decode()}})
            for kind, value in m["_parts"] if kind != "text" or value
        ]} for m in _merge_turns(req, "model")],
    }
    gc = {}
    if req.max_tokens:
        gc["maxOutputTokens"] = req.max_tokens
    if req.temperature is not None:
        gc["temperature"] = req.temperature
    if gc:
        body["generationConfig"] = gc
    in_tok = out_tok = 0
    stop = "stop"
    url = f"{base}/v1beta/models/{model}:streamGenerateContent?alt=sse"
    async with client.stream("POST", url, json=body, headers={"x-goog-api-key": api_key}) as r:
        if r.status_code >= 400:
            yield Error(_err_text(await r.aread(), r.status_code), f"upstream_{r.status_code}")
            return
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            for c in d.get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    if p.get("text"):
                        yield TextDelta(p["text"])
                if c.get("finishReason") == "MAX_TOKENS":
                    stop = "length"
            um = d.get("usageMetadata")
            if um:
                in_tok = um.get("promptTokenCount", in_tok)
                out_tok = um.get("candidatesTokenCount", out_tok) + um.get("thoughtsTokenCount", 0)
    yield Usage(in_tok, out_tok, None)
    yield Done(stop)  # type: ignore[arg-type]


def _err_text(raw: bytes, status: int) -> str:
    try:
        d = json.loads(raw)
        return str(d.get("error", {}).get("message") or d)[:500]
    except Exception:  # noqa: BLE001
        return f"upstream HTTP {status}: {raw[:200]!r}"
