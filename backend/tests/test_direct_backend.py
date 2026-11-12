import json

import httpx

from app.adapters.base import Done, Error, NormalizedRequest, TextDelta, Usage
from app.backends.direct import stream_direct


async def run(kind, handler, **kw):
    req = NormalizedRequest(model=kw.pop("model", "sonnet"), system="sys", turns=[("user", "a"), ("user", "b"), ("assistant", "c"), ("user", "d")])
    return [e async for e in stream_direct(kind, req, api_key="k", system_default="raw", extra={}, timeout=5,
                                           transport=httpx.MockTransport(handler), **kw)]  # fmt: skip


def sse(*events):
    return "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in events).encode()


async def test_anthropic_stream_and_request_shape():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["h"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200, content=sse(
            {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 4}},
        ), headers={"content-type": "text/event-stream"})

    evs = await run("claude", handler)
    assert "".join(e.text for e in evs if isinstance(e, TextDelta)) == "Hello"
    assert [e for e in evs if isinstance(e, Usage)][0].input_tokens == 11
    assert isinstance(evs[-1], Done)
    assert seen["url"].endswith("/v1/messages") and seen["h"]["x-api-key"] == "k"
    b = seen["body"]
    assert b["stream"] is True and b["model"].startswith("claude-") and "raw" in b["system"] and "sys" in b["system"]
    assert [m["role"] for m in b["messages"]] == ["user", "assistant", "user"]  # consecutive user turns merged
    assert b["messages"][0]["content"] == "a\n\nb"


async def test_anthropic_http_error():
    evs = await run("claude", lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    assert isinstance(evs[0], Error) and "bad key" in evs[0].message


async def test_gemini_stream():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["h"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200, content=sse(
            {"candidates": [{"content": {"parts": [{"text": "Hi "}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "there"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}},
        ))

    evs = await run("agy", handler, model="gemini-3.8-flash-low")
    assert "".join(e.text for e in evs if isinstance(e, TextDelta)) == "Hi there"
    u = [e for e in evs if isinstance(e, Usage)][0]
    assert (u.input_tokens, u.output_tokens) == (7, 3)
    assert "streamGenerateContent" in seen["url"] and "gemini-3.8-flash:" in seen["url"] and seen["h"]["x-goog-api-key"] == "k"
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]


async def test_missing_key_is_an_error_event():
    req = NormalizedRequest(model="sonnet", system="", turns=[("user", "x")])
    evs = [e async for e in stream_direct("claude", req, api_key="", system_default="", extra={}, timeout=5)]
    assert isinstance(evs[0], Error)


async def test_direct_backend_through_the_api(live, wrappers):
    """End to end: provider.backend=direct bypasses the CLI binary entirely."""
    from openai import OpenAI

    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "direct!"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}})))  # fmt: skip
    from tests import conftest  # the live server runs in-process, so its ServiceState can be patched

    LIVE_APP = conftest.LIVE_APP

    LIVE_APP.state.service.direct_transport = transport
    try:
        live.admin("POST", "/providers", json={"name": "dclaude", "kind": "claude", "enabled": True, "backend": "direct",
                                               "binary_path": "/nonexistent/claude", "default_model": "sonnet", "models": ["sonnet"]})  # fmt: skip
        live.admin("PUT", "/providers/dclaude/secret", json={"api_key": "sk-ant-x"})
        r = OpenAI(base_url=live.v1, api_key=live.key).chat.completions.create(model="dclaude/sonnet", messages=[{"role": "user", "content": "x"}])
        assert r.choices[0].message.content == "direct!" and r.usage.completion_tokens == 2
    finally:
        LIVE_APP.state.service.direct_transport = None


async def test_images_remain_in_their_original_turn_for_direct_backends():
    from app.adapters.base import Image
    seen = []
    image = Image("image/png", b"example")
    req = NormalizedRequest(model="sonnet", system="", turns=[("user", "first"), ("assistant", "answer"), ("user", "follow up")],
                            images=[image], images_by_turn={0: [image]})
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b"")
    for kind in ("claude", "gemini"):
        _ = [event async for event in stream_direct(kind, req, api_key="k", system_default="", extra={}, timeout=5,
                                                     transport=httpx.MockTransport(handler))]
    assert seen[0]["messages"][0]["content"][0]["type"] == "image"
    assert seen[0]["messages"][2]["content"] == "follow up"
    assert "inlineData" in seen[1]["contents"][0]["parts"][0]
    assert all("inlineData" not in part for part in seen[1]["contents"][2]["parts"])
