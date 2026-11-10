"""OpenAI-format conformance, using the official `openai` SDK against a live server (fake CLIs behind real adapters)."""
import os
import signal
import time

import httpx
import openai
import pytest
from openai import OpenAI

MSG = [{"role": "user", "content": "ping"}]


@pytest.fixture
def client(live):
    return OpenAI(base_url=live.v1, api_key=live.key, max_retries=0, timeout=30)


def test_models_lists_enabled_provider_model_ids(client):
    ids = {m.id for m in client.models.list().data}
    assert {"claude/sonnet", "claude/opus", "agy/gemini-3.8-flash-low", "txt/t1"} <= ids
    assert all("/" in i for i in ids)


@pytest.mark.parametrize("model", ["claude/sonnet", "agy/gemini-3.8-flash-low", "txt/t1"])
def test_non_streaming_shape(client, model):
    r = client.chat.completions.create(model=model, messages=MSG)
    assert r.id.startswith("chatcmpl-") and r.object == "chat.completion" and r.created > 1_600_000_000
    assert r.model == model
    c = r.choices[0]
    assert c.index == 0 and c.message.role == "assistant" and "ping" in c.message.content
    assert c.finish_reason == "stop"
    if not model.startswith("txt"):  # the custom text CLI reports no usage
        assert r.usage.prompt_tokens > 0 and r.usage.completion_tokens > 0
        assert r.usage.total_tokens == r.usage.prompt_tokens + r.usage.completion_tokens


@pytest.mark.parametrize("model", ["claude/sonnet", "agy/gemini-3.8-flash-low", "txt/t1"])
def test_streaming_matches_non_streaming(client, model):
    full = client.chat.completions.create(model=model, messages=MSG).choices[0].message.content
    chunks = list(client.chat.completions.create(model=model, messages=MSG, stream=True))
    assert chunks[0].choices[0].delta.role == "assistant"
    assert all(c.object == "chat.completion.chunk" and c.id == chunks[0].id for c in chunks)
    assert "".join(c.choices[0].delta.content or "" for c in chunks if c.choices) == full
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert sum(1 for c in chunks if c.choices and c.choices[0].finish_reason) == 1


def test_stream_include_usage(client):
    chunks = list(client.chat.completions.create(model="claude/sonnet", messages=MSG, stream=True,
                                                 stream_options={"include_usage": True}))  # fmt: skip
    last = chunks[-1]
    assert last.choices == [] and last.usage.total_tokens > 0


def test_raw_sse_framing(live):
    with httpx.stream("POST", live.v1 + "/chat/completions", headers={"Authorization": f"Bearer {live.key}"},
                      json={"model": "claude/sonnet", "messages": MSG, "stream": True}, timeout=30) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = [ln for ln in r.iter_lines() if ln]
    assert all(ln.startswith("data: ") for ln in lines)
    assert lines[-1] == "data: [DONE]"


def test_system_and_multi_turn_mapping(client):
    r = client.chat.completions.create(model="claude/sonnet", messages=[
        {"role": "system", "content": "Be brief."}, {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"}, {"role": "user", "content": "second question"}])  # fmt: skip
    assert "[sys=yes]" in r.choices[0].message.content and "second question" in r.choices[0].message.content


def test_content_parts_are_accepted(client):
    r = client.chat.completions.create(model="claude/sonnet", messages=[{"role": "user", "content": [{"type": "text", "text": "partsy"}]}])
    assert "partsy" in r.choices[0].message.content


def test_unsupported_temperature_reported_in_header(live):
    r = httpx.post(live.v1 + "/chat/completions", headers={"Authorization": f"Bearer {live.key}"}, timeout=30,
                   json={"model": "claude/sonnet", "messages": MSG, "temperature": 0.2, "max_tokens": 5})  # fmt: skip
    assert r.status_code == 200
    assert set(r.headers["x-proxy-ignored-params"].split(",")) == {"temperature", "max_tokens"}


# ---- errors are OpenAI-shaped --------------------------------------------------------------------
def test_bad_key(live):
    with pytest.raises(openai.AuthenticationError) as e:
        OpenAI(base_url=live.v1, api_key="sk-proxy-nope", max_retries=0).chat.completions.create(model="claude/sonnet", messages=MSG)
    assert e.value.body["code"] == "invalid_api_key"


def test_missing_key_returns_openai_error_json(live):
    r = httpx.post(live.v1 + "/chat/completions", json={"model": "claude/sonnet", "messages": MSG})
    assert r.status_code == 401 and set(r.json()["error"]) >= {"message", "type", "code"}


def test_unknown_model(client):
    with pytest.raises(openai.NotFoundError) as e:
        client.chat.completions.create(model="claude/does-not-exist", messages=MSG)
    assert e.value.body["code"] == "model_not_found"
    with pytest.raises(openai.NotFoundError):
        client.chat.completions.create(model="nope/x", messages=MSG)


def test_invalid_body(live):
    h = {"Authorization": f"Bearer {live.key}"}
    r = httpx.post(live.v1 + "/chat/completions", headers=h, json={"model": "claude/sonnet"})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"
    r = httpx.post(live.v1 + "/chat/completions", headers=h, content=b"{oops", )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_json"


def test_body_size_limit(live):
    def post(n_bytes):
        return httpx.post(live.v1 + "/chat/completions", headers={"Authorization": f"Bearer {live.key}"}, timeout=30,
                          json={"model": "claude/sonnet", "messages": [{"role": "user", "content": "x" * n_bytes}]})  # fmt: skip

    # the body limit leaves room for base64 images, so prompt text has its own, smaller cap
    r = post(300 * 1024)
    assert r.status_code == 413 and r.json()["error"]["code"] == "context_length_exceeded"
    r = post(11 * 1024 * 1024)
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"


def test_cli_crash_becomes_502_with_stderr(client):
    with pytest.raises(openai.APIStatusError) as e:
        client.chat.completions.create(model="claude/sonnet", messages=[{"role": "user", "content": "FAKE_CRASH"}])
    assert e.value.status_code == 502 and "boom" in e.value.message


def test_cli_reported_error_before_stream_is_http_error(client):
    with pytest.raises(openai.APIStatusError) as e:
        client.chat.completions.create(model="claude/sonnet", stream=True, messages=[{"role": "user", "content": "FAKE_ERROR"}])
    assert e.value.status_code == 502


def test_error_after_streaming_started_is_an_in_band_error_chunk(live):
    """Once a 200 is committed the only honest signal is an error event followed by [DONE]."""
    import json

    with httpx.stream("POST", live.v1 + "/chat/completions", headers={"Authorization": f"Bearer {live.key}"},
                      json={"model": "claude/sonnet", "stream": True, "messages": [{"role": "user", "content": "FAKE_MIDERROR"}]}) as r:
        assert r.status_code == 200
        payloads = [ln[6:] for ln in r.iter_lines() if ln.startswith("data: ")]
    assert payloads[-1] == "[DONE]"
    assert "error" in json.loads(payloads[-2]) and json.loads(payloads[-2])["error"]["code"] == "cli_error"


def test_agy_reported_error(client):
    with pytest.raises(openai.APIStatusError):
        client.chat.completions.create(model="agy/gemini-3.8-flash-low", messages=[{"role": "user", "content": "FAKE_ERROR"}])


# ---- credits ---------------------------------------------------------------------------------------
def test_ledger_debits_cli_reported_cost(live):
    uid, key = live.new_user("billing", 1.0)
    c = OpenAI(base_url=live.v1, api_key=key, max_retries=0)
    c.chat.completions.create(model="claude/sonnet", messages=MSG)
    me = httpx.get(live.v1 + "/me", headers={"Authorization": f"Bearer {key}"}).json()
    assert me["requests"] == 1 and me["spent_usd"] == pytest.approx(0.0123) and me["credits_usd"] == pytest.approx(1.0 - 0.0123)
    rows = live.admin("GET", f"/ledger?user_id={uid}")
    assert rows[0]["provider"] == "claude" and rows[0]["estimated"] is False and rows[0]["status"] == "ok"


def test_agy_cost_is_estimated_from_tokens(live):
    uid, key = live.new_user("billing-agy", 1.0)
    OpenAI(base_url=live.v1, api_key=key, max_retries=0).chat.completions.create(model="agy/gemini-3.8-flash-low", messages=MSG)
    row = live.admin("GET", f"/ledger?user_id={uid}")[0]
    assert row["estimated"] is True and row["input_tokens"] > 0


def test_zero_balance_is_rejected_and_topup_restores(live):
    uid, key = live.new_user("broke", 0.0)
    c = OpenAI(base_url=live.v1, api_key=key, max_retries=0)
    with pytest.raises(openai.RateLimitError) as e:
        c.chat.completions.create(model="claude/sonnet", messages=MSG)
    assert e.value.body["code"] == "insufficient_quota"
    assert live.admin("POST", f"/users/{uid}/topup", json={"amount_usd": 1.0})["credits_usd"] == 1.0
    assert c.chat.completions.create(model="claude/sonnet", messages=MSG).choices


def test_revoked_key_stops_working(live):
    uid, key = live.new_user("revoke-me", 1.0)
    kid = next(k["id"] for k in live.admin("GET", "/keys") if k["user_id"] == uid)
    live.admin("DELETE", f"/keys/{kid}")
    with pytest.raises(openai.AuthenticationError):
        OpenAI(base_url=live.v1, api_key=key, max_retries=0).models.list()


def test_keys_are_stored_hashed(live):
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import ApiKey

    with session_scope() as s:
        assert all(k.key_hash != live.key and live.key not in k.key_hash for k in s.scalars(select(ApiKey)))


# ---- process-group kill on client disconnect -----------------------------------------------------
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_client_disconnect_kills_the_cli(live, tmp_path):
    pidfile = tmp_path / "pid"
    with httpx.Client(timeout=30) as c, c.stream(
        "POST", live.v1 + "/chat/completions", headers={"Authorization": f"Bearer {live.key}"},
        json={"model": "claude/sonnet", "stream": True, "messages": [{"role": "user", "content": f"FAKE_SLOW FAKE_PIDFILE={pidfile} " + "word " * 40}]},
    ) as r:  # fmt: skip
        it = r.iter_lines()
        for _ in range(4):
            next(it)
        pid = int(pidfile.read_text())
        assert _alive(pid)
    # the `with` exit closed the socket mid-stream
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "CLI process survived a client disconnect"


def test_non_streaming_disconnect_kills_the_cli(live, tmp_path):
    pidfile = tmp_path / "pid2"
    with pytest.raises(httpx.ReadTimeout):
        httpx.post(live.v1 + "/chat/completions", headers={"Authorization": f"Bearer {live.key}"}, timeout=2,
                   json={"model": "claude/sonnet", "messages": [{"role": "user", "content": f"FAKE_SLEEP FAKE_PIDFILE={pidfile}"}]})  # fmt: skip
    pid = int(pidfile.read_text())
    for _ in range(80):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "CLI process survived a client disconnect"
