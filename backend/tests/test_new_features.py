"""Codex/Gemini adapters, tool calling, images, Anthropic endpoint, per-key limits, metrics, migrations, Redis."""
import base64
import datetime as dt
import json
import os
from pathlib import Path

import httpx
import pytest

from app import toolcall
from app.adapters.base import Done, Error, Image, NormalizedRequest, RunContext, TextDelta, ToolEvent, Usage
from app.adapters.claude import ClaudeAdapter
from app.adapters.codex import CodexAdapter
from app.adapters.gemini import GeminiAdapter

FIXTURES = Path(__file__).parent / "fixtures"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
DATA_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()
WEATHER = {"type": "function", "function": {"name": "get_weather", "description": "Weather for a city",
                                            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}  # fmt: skip


def ctx(tmp_path: Path, **kw) -> RunContext:
    base = dict(provider_name="p", mode="raw", auth_mode="api_key", workdir=tmp_path, home=tmp_path / "home",
                binary="/bin/x", raw_system_prompt="RAW PROMPT", api_key=None, max_budget_usd=0.25, extra={})  # fmt: skip
    base.update(kw)
    return RunContext(**base)


def req(text="hi", model="default", system="", images=()) -> NormalizedRequest:
    return NormalizedRequest(model=model, system=system, turns=[("user", text)], images=list(images))


def auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def chat(live, key=None, **body):
    body.setdefault("messages", [{"role": "user", "content": "hello"}])
    return httpx.post(live.v1 + "/chat/completions", headers=auth(key or live.key), json=body, timeout=30)


# ---- codex adapter -------------------------------------------------------------------------------
def test_codex_parses_real_capture():
    a = CodexAdapter()
    evs = [e for ln in (FIXTURES / "codex_stream.ndjson").read_text().splitlines() for e in a.parse_line(ln)]
    assert [e.text for e in evs if isinstance(e, TextDelta)] == ["51"]
    usage = next(e for e in evs if isinstance(e, Usage))
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (18484, 5, None)  # cached tokens are not added twice
    assert isinstance(evs[-1], Done)


def test_codex_failure_and_multiple_messages():
    a = CodexAdapter()
    assert isinstance(a.parse_line('{"type":"turn.failed","error":{"message":"quota"}}')[0], Error)
    assert isinstance(a.parse_line('{"type":"error","message":"reconnecting"}')[0], ToolEvent)  # not fatal on its own
    b = CodexAdapter()
    one = b.parse_line('{"type":"item.completed","item":{"type":"agent_message","text":"a"}}')
    two = b.parse_line('{"type":"item.completed","item":{"type":"agent_message","text":"b"}}')
    assert one[0].text + two[0].text == "a\n\nb"
    assert isinstance(b.parse_line('{"type":"item.completed","item":{"type":"command_execution","command":"ls"}}')[0], ToolEvent)


def test_codex_raw_command(tmp_path):
    a = CodexAdapter()
    c = ctx(tmp_path, api_key="sk-x", skip_permissions=True, extra={"extra_args": ["--oss"]})
    r = req(model="gpt-x", system="Be terse.", images=[Image("image/png", PNG)])
    a.prepare_workdir(r, c)
    agents = (tmp_path / "AGENTS.md").read_text()
    assert "RAW PROMPT" in agents and "Be terse." in agents
    cmd = a.build_command(r, c)
    v = cmd.argv
    assert v[:3] == ["/bin/x", "exec", "--json"] and v[-1] == "-" and cmd.stdin_data == "hi"
    assert "--ephemeral" in v and "--skip-git-repo-check" in v and v[v.index("-m") + 1] == "gpt-x"
    assert v[v.index("-s") + 1] == "read-only" and "--ignore-user-config" in v
    assert "--dangerously-bypass-approvals-and-sandbox" not in v and "--oss" not in v  # never in raw mode
    img = Path(v[v.index("-i") + 1])
    assert img.read_bytes() == PNG and img.parent == tmp_path
    assert cmd.env["CODEX_API_KEY"] == "sk-x" and cmd.env["CODEX_HOME"] == str(tmp_path / "home" / ".codex")


def test_codex_agent_command_and_default_model(tmp_path):
    c = ctx(tmp_path, mode="agent", skip_permissions=True, use_host_home=True, extra={"extra_args": ["--oss"]})
    v = CodexAdapter().build_command(req(), c).argv
    assert "-m" not in v  # "default" = let the CLI choose
    assert "--dangerously-bypass-approvals-and-sandbox" in v and "--oss" in v
    v = CodexAdapter().build_command(req(), ctx(tmp_path, mode="agent")).argv
    assert v[v.index("-s") + 1] == "workspace-write"


# ---- gemini adapter ------------------------------------------------------------------------------
def test_gemini_stream_json():
    a = GeminiAdapter()
    lines = [
        '{"type":"init","session_id":"s","model":"auto"}',
        '{"type":"message","role":"user","content":"hi"}',
        '{"type":"message","role":"assistant","content":"Hel","delta":true}',
        '{"type":"message","role":"assistant","content":"lo","delta":true}',
        '{"type":"message","role":"assistant","content":"Hello","delta":false}',
        '{"type":"tool_use","tool_name":"x"}',
        '{"type":"result","status":"success","stats":{"input_tokens":12,"output_tokens":3}}',
    ]
    evs = [e for ln in lines for e in a.parse_line(ln)]
    assert "".join(e.text for e in evs if isinstance(e, TextDelta)) == "Hello"  # user echo and the repeat are dropped
    u = next(e for e in evs if isinstance(e, Usage))
    assert (u.input_tokens, u.output_tokens) == (12, 3) and isinstance(evs[-1], Done)


def test_gemini_json_format_per_model_stats_and_errors():
    a = GeminiAdapter()
    evs = a.parse_line(json.dumps({"response": "42", "stats": {"models": {"m": {"tokens": {"prompt": 9, "candidates": 2, "thoughts": 1}}}}}))
    assert evs[0].text == "42" and (evs[1].input_tokens, evs[1].output_tokens) == (9, 3)
    assert isinstance(GeminiAdapter().parse_line('{"type":"result","status":"error","error":{"message":"nope"}}')[0], Error)
    b = GeminiAdapter()
    assert isinstance(b.parse_line('{"type":"error","message":"quota hit"}')[0], ToolEvent)
    assert b.parse_line('{"type":"result","status":"error"}')[0].message == "quota hit"


def test_gemini_command(tmp_path):
    a = GeminiAdapter()
    c = ctx(tmp_path, api_key="g-key")
    r = req(model="flash", system="Be terse.")
    a.prepare_workdir(r, c)
    cmd = a.build_command(r, c)
    v = cmd.argv
    assert v[v.index("-p") + 1] == "hi" and v[v.index("-m") + 1] == "flash" and v[v.index("--output-format") + 1] == "stream-json"
    assert v[v.index("--approval-mode") + 1] == "default"
    assert cmd.env["GEMINI_API_KEY"] == "g-key"
    sysfile = Path(cmd.env["GEMINI_SYSTEM_MD"])
    assert "RAW PROMPT" in sysfile.read_text() and "Be terse." in sysfile.read_text()
    v = GeminiAdapter().build_command(req(), ctx(tmp_path, mode="agent", skip_permissions=True)).argv
    assert v[v.index("--approval-mode") + 1] == "yolo" and "-m" not in v


def test_claude_image_command(tmp_path):
    cmd = ClaudeAdapter().build_command(req(model="haiku", images=[Image("image/png", PNG)]), ctx(tmp_path))
    assert cmd.argv[cmd.argv.index("--input-format") + 1] == "stream-json"
    msg = json.loads(cmd.stdin_data)
    blocks = msg["message"]["content"]
    assert msg["type"] == "user" and blocks[0]["source"]["media_type"] == "image/png" and blocks[-1] == {"type": "text", "text": "hi"}
    assert base64.b64decode(blocks[0]["source"]["data"]) == PNG
    assert "--input-format" not in ClaudeAdapter().build_command(req(model="haiku"), ctx(tmp_path)).argv


def test_extra_args_only_in_agent_mode(tmp_path):
    ex = {"extra_args": ["--agent", "reviewer"]}
    assert "--agent" not in ClaudeAdapter().build_command(req(model="haiku"), ctx(tmp_path, extra=ex)).argv
    assert "reviewer" in ClaudeAdapter().build_command(req(model="haiku"), ctx(tmp_path, mode="agent", extra=ex)).argv


# ---- live: codex + gemini through the API --------------------------------------------------------
@pytest.mark.parametrize("provider", ["codex", "gemini"])
def test_new_providers_chat_and_stream(live, provider):
    r = chat(live, model=f"{provider}/default", messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "ping"}])
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == f"FAKE[{provider}-default][sys=yes] ping"
    assert r.json()["usage"]["completion_tokens"] > 0
    with httpx.stream("POST", live.v1 + "/chat/completions", headers=auth(live.key), timeout=30,
                      json={"model": f"{provider}/default", "stream": True, "messages": [{"role": "user", "content": "ping"}]}) as s:  # fmt: skip
        body = "".join(s.iter_text())
    assert "ping" in body and body.rstrip().endswith("data: [DONE]")


@pytest.mark.parametrize("provider", ["codex", "gemini"])
def test_new_providers_report_errors(live, provider):
    r = chat(live, model=f"{provider}/default", messages=[{"role": "user", "content": "FAKE_ERROR"}])
    assert r.status_code == 502 and f"fake {provider} failure" in r.json()["error"]["message"]


# ---- tool calling --------------------------------------------------------------------------------
def test_toolcall_parse_and_render():
    tools = [toolcall.ToolSpec("get_weather", "w", {"type": "object"})]
    text, calls = toolcall.parse('Sure.\n<tool_call>```json\n{"name":"get_weather","arguments":{"city":"Oslo"}}\n```</tool_call>', tools)
    assert text == "Sure." and calls[0].name == "get_weather" and calls[0].arguments == {"city": "Oslo"}
    # unknown function / broken JSON are left alone as plain text
    for bad in ('<tool_call>{"name":"rm_rf","arguments":{}}</tool_call>', "<tool_call>{oops</tool_call>"):
        assert toolcall.parse(bad, tools) == (bad, [])
    assert toolcall.parse("plain answer", tools) == ("plain answer", [])
    assert '"city":"Oslo"' in toolcall.render_call("get_weather", '{"city": "Oslo"}')
    assert "MUST call the function `get_weather`" in toolcall.instructions(tools, "get_weather")


def test_openai_tool_call_round_trip(live):
    r = chat(live, model="claude/haiku", tools=[WEATHER], messages=[{"role": "user", "content": "FAKE_TOOLCALL weather in Paris?"}])
    assert r.status_code == 200, r.text
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls" and choice["message"]["content"] == "Let me check."
    call = choice["message"]["tool_calls"][0]
    assert call["type"] == "function" and call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}

    # second turn: the tool result goes back in; the model now answers in plain text
    r2 = chat(live, model="claude/haiku", tools=[WEATHER], messages=[
        {"role": "user", "content": "FAKE_TOOLCALL weather in Paris?"},
        {"role": "assistant", "content": "Let me check.", "tool_calls": [call]},
        {"role": "tool", "tool_call_id": call["id"], "content": "18C and sunny"},
        {"role": "user", "content": "FAKE_SYSTEM"},
    ])  # fmt: skip
    msg = r2.json()["choices"][0]
    assert msg["finish_reason"] == "stop" and "tool_calls" not in msg["message"]
    assert "# Functions" in msg["message"]["content"] and "get_weather" in msg["message"]["content"]  # schemas reached the CLI


def test_openai_tool_call_streaming_and_tool_choice_none(live):
    with httpx.stream("POST", live.v1 + "/chat/completions", headers=auth(live.key), timeout=30, json={
        "model": "agy/gemini-3.8-flash-low", "stream": True, "tools": [WEATHER], "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": "FAKE_TOOLCALL"}]}) as s:  # fmt: skip
        chunks = [json.loads(ln[6:]) for ln in s.iter_lines() if ln.startswith("data: {")]
    deltas = [c["choices"][0] for c in chunks if c["choices"]]
    tc = next(d["delta"]["tool_calls"] for d in deltas if d["delta"].get("tool_calls"))
    assert tc[0]["index"] == 0 and tc[0]["function"]["name"] == "get_weather"
    assert deltas[-1]["finish_reason"] == "tool_calls" and chunks[-1]["usage"]["total_tokens"] > 0

    r = chat(live, model="claude/haiku", tools=[WEATHER], tool_choice="none", messages=[{"role": "user", "content": "FAKE_SYSTEM"}])
    assert "# Functions" not in r.json()["choices"][0]["message"]["content"]
    r = chat(live, model="claude/haiku", tools=[WEATHER], tool_choice={"type": "function", "function": {"name": "nope"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_tool_choice"


# ---- images --------------------------------------------------------------------------------------
def _img_msg(text):
    return [{"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": DATA_URL}}]}]


def test_images_reach_supporting_clis(live):
    for model in ("claude/haiku", "codex/default"):
        r = chat(live, model=model, messages=_img_msg("FAKE_IMAGES"))
        assert r.status_code == 200, r.text
        assert r.json()["choices"][0]["message"]["content"] == "IMAGES=1", model


def test_images_rejected_where_unsupported(live):
    r = chat(live, model="agy/gemini-3.8-flash-low", messages=_img_msg("x"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_content" and "direct API backend" in r.json()["error"]["message"]
    r = chat(live, model="claude/haiku", messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]}])
    assert r.status_code == 400 and "not fetched" in r.json()["error"]["message"]
    r = chat(live, model="claude/haiku", messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,"}}]}])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_image"


# ---- Anthropic-compatible endpoint ---------------------------------------------------------------
def messages(live, key=None, **body):
    body.setdefault("max_tokens", 100)
    return httpx.post(live.v1 + "/messages", headers={"x-api-key": key or live.key, "anthropic-version": "2023-06-01"}, json=body, timeout=30)


def test_anthropic_messages_basic(live):
    r = messages(live, model="claude/haiku", system=[{"type": "text", "text": "sys"}], messages=[{"role": "user", "content": "ping"}])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "message" and d["role"] == "assistant" and d["id"].startswith("msg_") and d["model"] == "claude/haiku"
    assert d["content"] == [{"type": "text", "text": "FAKE[haiku][sys=yes] ping"}]
    assert d["stop_reason"] == "end_turn" and d["usage"]["input_tokens"] > 0 and d["usage"]["output_tokens"] > 0


def test_anthropic_messages_stream(live):
    with httpx.stream("POST", live.v1 + "/messages", headers={"x-api-key": live.key}, timeout=30,
                      json={"model": "codex/default", "max_tokens": 50, "stream": True, "messages": [{"role": "user", "content": "ping"}]}) as s:  # fmt: skip
        assert s.status_code == 200
        lines = list(s.iter_lines())
    names = [ln[7:] for ln in lines if ln.startswith("event: ")]
    assert names[:2] == ["message_start", "content_block_start"] and names[-3:] == ["content_block_stop", "message_delta", "message_stop"]
    datas = [json.loads(ln[6:]) for ln in lines if ln.startswith("data: ")]
    text = "".join(d["delta"]["text"] for d in datas if d["type"] == "content_block_delta")
    assert text.endswith("ping")
    md = next(d for d in datas if d["type"] == "message_delta")
    assert md["delta"]["stop_reason"] == "end_turn" and md["usage"]["output_tokens"] > 0


def test_anthropic_tool_use_and_image(live):
    tools = [{"name": "get_weather", "description": "w", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}]
    r = messages(live, model="claude/haiku", tools=tools, messages=[{"role": "user", "content": "FAKE_TOOLCALL"}])
    d = r.json()
    assert d["stop_reason"] == "tool_use", d
    tu = d["content"][-1]
    assert tu["type"] == "tool_use" and tu["name"] == "get_weather" and tu["input"] == {"city": "Paris"} and tu["id"].startswith("toolu_")
    r = messages(live, model="claude/haiku", tools=tools, messages=[
        {"role": "user", "content": "FAKE_TOOLCALL"},
        {"role": "assistant", "content": d["content"]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu["id"], "content": [{"type": "text", "text": "18C"}]}]},
    ])  # fmt: skip
    assert r.status_code == 200 and r.json()["stop_reason"] == "end_turn"

    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(PNG).decode()}}
    r = messages(live, model="claude/haiku", messages=[{"role": "user", "content": [img, {"type": "text", "text": "FAKE_IMAGES"}]}])
    assert r.json()["content"][0]["text"] == "IMAGES=1"


def test_anthropic_errors_and_count_tokens(live):
    r = httpx.post(live.v1 + "/messages", headers={"x-api-key": "sk-proxy-bogus"}, json={"model": "claude/haiku", "messages": []})
    assert r.status_code == 401 and r.json() == {"type": "error", "error": {"type": "authentication_error", "message": "Invalid API key"}}
    r = messages(live, model="nope/x", messages=[{"role": "user", "content": "hi"}])
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found_error"
    r = messages(live, model="claude/haiku", messages=[{"role": "user", "content": "FAKE_ERROR"}])
    assert r.status_code == 502 and r.json()["type"] == "error"
    r = httpx.post(live.v1 + "/messages/count_tokens", headers={"x-api-key": live.key},
                   json={"model": "claude/haiku", "messages": [{"role": "user", "content": "x" * 400}]})  # fmt: skip
    assert 90 <= r.json()["input_tokens"] <= 120


# ---- per-key limits ------------------------------------------------------------------------------
def test_key_model_allow_list(live):
    uid, _ = live.new_user("limits-models")
    k = live.admin("POST", "/keys", json={"user_id": uid, "allowed_models": ["claude/haiku", "txt/*"]})
    assert k["allowed_models"] == ["claude/haiku", "txt/*"]
    assert chat(live, k["key"], model="claude/haiku").status_code == 200
    assert chat(live, k["key"], model="txt/t1").status_code == 200
    r = chat(live, k["key"], model="agy/gemini-3.8-flash-low")
    assert r.status_code == 403 and r.json()["error"]["code"] == "model_not_allowed"
    ids = [m["id"] for m in httpx.get(live.v1 + "/models", headers=auth(k["key"])).json()["data"]]
    assert ids and all(i == "claude/haiku" or i.startswith("txt/") for i in ids)


def test_key_budget(live):
    uid, _ = live.new_user("limits-budget")
    k = live.admin("POST", "/keys", json={"user_id": uid, "budget_usd": 0.02})  # the fake claude bills $0.0123 a call
    assert chat(live, k["key"], model="claude/haiku").status_code == 200
    me = httpx.get(live.v1 + "/me", headers=auth(k["key"])).json()
    assert me["key_budget_usd"] == 0.02 and me["key_spent_usd"] == pytest.approx(0.0123) and me["key_remaining_usd"] == pytest.approx(0.0077)
    assert chat(live, k["key"], model="claude/haiku").status_code == 200  # still some budget left before this one
    r = chat(live, k["key"], model="claude/haiku")
    assert r.status_code == 429 and r.json()["error"]["code"] == "key_budget_exhausted"
    row = next(x for x in live.admin("GET", "/keys") if x["id"] == k["id"])
    assert row["spent_usd"] == pytest.approx(0.0246) and row["budget_usd"] == 0.02
    # raising the budget un-blocks the key; null clears it
    live.admin("PATCH", f"/keys/{k['id']}", json={"budget_usd": 1.0})
    assert chat(live, k["key"], model="claude/haiku").status_code == 200
    assert live.admin("PATCH", f"/keys/{k['id']}", json={"budget_usd": None})["budget_usd"] is None


def test_key_expiry(live):
    uid, _ = live.new_user("limits-expiry")
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
    k = live.admin("POST", "/keys", json={"user_id": uid, "expires_at": past})
    r = chat(live, k["key"], model="claude/haiku")
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"]
    k2 = live.admin("POST", "/keys", json={"user_id": uid, "expires_in_days": 1})
    assert chat(live, k2["key"], model="claude/haiku").status_code == 200
    exp = dt.datetime.fromisoformat(k2["expires_at"])
    assert exp.tzinfo is not None and dt.timedelta(hours=23) < exp - dt.datetime.now(dt.timezone.utc) < dt.timedelta(hours=25)


# ---- timestamps, test runs, usage chart, metrics -------------------------------------------------
def test_timestamps_carry_utc_offset(live):
    chat(live, model="claude/haiku")
    for row in live.admin("GET", "/ledger?limit=5") + live.admin("GET", "/keys"):
        ts = row["created_at"]
        assert ts.endswith("+00:00"), ts
        assert abs(dt.datetime.fromisoformat(ts) - dt.datetime.now(dt.timezone.utc)) < dt.timedelta(hours=1)


def test_admin_test_runs_are_logged_but_not_billed(live):
    before = live.admin("GET", "/users")
    out = live.admin("POST", "/providers/claude/test", json={"prompt": "ping"})
    assert out["ok"]
    row = live.admin("GET", "/ledger?limit=1")[0]
    assert row["user_id"] is None and row["request_id"].startswith("test-") and row["cost_usd"] == pytest.approx(0.0123)
    assert live.admin("GET", "/users") == before  # nobody's balance or usage changed


def test_daily_usage(live):
    chat(live, model="claude/haiku")
    days = live.admin("GET", "/usage/daily?days=7")
    assert len(days) == 7 and days[-1]["date"] == dt.datetime.now(dt.timezone.utc).date().isoformat()
    today = days[-1]
    assert today["requests"] >= 1 and today["by_provider"]["claude"] > 0
    assert today["cost_usd"] == pytest.approx(sum(today["by_provider"].values()))


def test_metrics_endpoint(live):
    chat(live, model="claude/haiku")
    assert httpx.get(live.base + "/metrics").status_code == 401
    r = httpx.get(live.base + "/metrics", headers={"Authorization": "Bearer test-admin-token"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert 'proxy_requests_total{model="haiku",provider="claude",status="ok"}' in r.text
    assert 'proxy_tokens_total{direction="input",model="haiku",provider="claude"}' in r.text
    assert "proxy_queue_running 0" in r.text and "# TYPE proxy_cost_usd_total counter" in r.text


# ---- agent mode pinned to a project directory ----------------------------------------------------
def test_agent_workdir_and_extra_args(live, tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    live.admin("POST", "/providers", json={
        "name": "cxagent", "kind": "codex", "enabled": True, "mode": "agent", "auth_mode": "api_key",
        "binary_path": live.wrappers["codex"], "default_model": "default", "models": ["default"],
        "extra": {"workdir": str(project), "extra_args": ["--oss"]}})  # fmt: skip
    r = chat(live, model="cxagent/default", messages=[{"role": "system", "content": "House rules."}, {"role": "user", "content": "FAKE_ARGV"}])
    argv = json.loads(r.json()["choices"][0]["message"]["content"].removeprefix("ARGV="))
    assert argv[argv.index("-C") + 1] == str(project) and "--oss" in argv
    assert list(project.iterdir()) == []  # the proxy wrote nothing into the project (no AGENTS.md, no images)
    live.admin("PUT", "/providers/cxagent", json={"extra": {"workdir": str(tmp_path / "missing")}})
    r = chat(live, model="cxagent/default")
    assert r.status_code == 502 and r.json()["error"]["code"] == "bad_workdir"


# ---- schema migration ----------------------------------------------------------------------------
OLD_SCHEMA = """
CREATE TABLE users (id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, credits_usd FLOAT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), UNIQUE (name));
CREATE TABLE api_keys (id INTEGER NOT NULL, user_id INTEGER NOT NULL, label VARCHAR(100) NOT NULL, prefix VARCHAR(32) NOT NULL, key_hash VARCHAR(64) NOT NULL,
  revoked BOOLEAN NOT NULL, created_at DATETIME NOT NULL, last_used_at DATETIME, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE);
CREATE TABLE ledger (id INTEGER NOT NULL, request_id VARCHAR(64) NOT NULL, user_id INTEGER NOT NULL, provider VARCHAR(64) NOT NULL, model VARCHAR(128) NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_usd FLOAT NOT NULL, estimated BOOLEAN NOT NULL, status VARCHAR(16) NOT NULL,
  created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE);
CREATE INDEX ix_ledger_user_id ON ledger (user_id);
CREATE INDEX ix_ledger_created_at ON ledger (created_at);
CREATE INDEX ix_ledger_request_id ON ledger (request_id);
INSERT INTO users VALUES (1, 'me', 4.99, '2026-10-25 18:41:27.000000');
INSERT INTO api_keys VALUES (1, 1, 'local', 'sk-proxy-abcd', 'h', 0, '2026-10-25 18:41:27.000000', NULL);
INSERT INTO ledger VALUES (1, 'chatcmpl-1', 1, 'claude', 'haiku', 624, 4, 0.00013, 0, 'ok', '2026-10-25 18:41:29.000000');
INSERT INTO ledger VALUES (2, 'chatcmpl-2', 1, 'agy', 'gemini-3.8-flash-low', 6977, 2, 0.0021, 1, 'ok', '2026-10-25 18:46:29.000000');
"""


def test_migration_upgrades_a_0_1_database(tmp_path):
    import sqlite3

    from sqlalchemy import create_engine, inspect, text

    from app.db import Base, migrate

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(OLD_SCHEMA)
    con.close()
    eng = create_engine(f"sqlite:///{db}")
    for _ in range(2):  # second run must be a no-op
        Base.metadata.create_all(eng)
        migrate(eng)
    insp = inspect(eng)
    assert {"budget_usd", "expires_at", "allowed_models"} <= {c["name"] for c in insp.get_columns("api_keys")}
    cols = {c["name"]: c for c in insp.get_columns("ledger")}
    assert "key_id" in cols and cols["user_id"]["nullable"]
    assert {i["name"] for i in insp.get_indexes("ledger")} >= {"ix_ledger_user_id", "ix_ledger_created_at", "ix_ledger_request_id"}
    with eng.begin() as c:
        rows = c.execute(text("SELECT id, request_id, user_id, model, cost_usd FROM ledger ORDER BY id")).all()
        assert rows == [(1, "chatcmpl-1", 1, "haiku", 0.00013), (2, "chatcmpl-2", 1, "gemini-3.8-flash-low", 0.0021)]
        c.execute(text("INSERT INTO ledger (request_id, user_id, provider, model, input_tokens, output_tokens, cost_usd, estimated, status, created_at) "
                       "VALUES ('test-1', NULL, 'claude', 'haiku', 1, 1, 0, 0, 'ok', '2026-11-10 00:00:00')"))  # fmt: skip
        assert "ledger_old" not in insp.get_table_names()


# ---- Redis-backed queue and rate limiter ---------------------------------------------------------
def _redis_clients():
    """Real Redis when REDIS_TEST_URL is set, otherwise the in-memory fake."""
    url = os.environ.get("REDIS_TEST_URL")
    if url:
        import redis
        import redis.asyncio as aioredis

        return redis.Redis.from_url(url), aioredis.from_url(url)
    import fakeredis

    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server), fakeredis.FakeAsyncRedis(server=server)


async def test_redis_queue_limits_and_releases():
    import asyncio
    import uuid

    from app.runner.queue import QueueTimeout, RedisJobQueue

    _, r = _redis_clients()
    prefix = "t" + uuid.uuid4().hex[:8]
    # two "instances" sharing one Redis: 2 slots globally, 1 per user
    a = RedisJobQueue("", 2, 1, 0.4, client=r, prefix=prefix)
    b = RedisJobQueue("", 2, 1, 0.4, client=r, prefix=prefix)
    async with a.slot(1):
        with pytest.raises(QueueTimeout):  # same user, other instance: per-user limit holds across instances
            async with b.slot(1):
                pass
        async with b.slot(2):
            assert a.stats()["running"] == 1 and b.stats()["running"] == 1
            with pytest.raises(QueueTimeout):  # global limit of 2 is full
                async with a.slot(3):
                    pass
    async with b.slot(1):  # everything was released
        async with a.slot(3):
            pass
    assert await r.zcard(f"{prefix}:slots:global") == 0

    # a crashed holder's slot frees itself when its lease runs out
    c = RedisJobQueue("", 1, 1, 2.0, client=r, prefix=prefix + "x", lease_s=0.3)
    await r.zadd(f"{prefix}x:slots:global", {"dead-holder": __import__("time").time() + 0.3})
    t0 = asyncio.get_event_loop().time()
    async with c.slot(9):
        assert asyncio.get_event_loop().time() - t0 >= 0.2
    await r.aclose()


def test_redis_rate_limiter():
    import uuid

    from app.errors import ProxyError
    from app.ratelimit import RedisRateLimiter

    r, _ = _redis_clients()
    prefix = "t" + uuid.uuid4().hex[:8]
    one, two = RedisRateLimiter("", 3, client=r, prefix=prefix), RedisRateLimiter("", 3, client=r, prefix=prefix)
    one.check(7), two.check(7), one.check(7)  # the count is shared between instances
    with pytest.raises(ProxyError) as e:
        two.check(7)
    assert e.value.status == 429 and int(e.value.headers["Retry-After"]) >= 1
    two.check(8)  # other keys are unaffected
    RedisRateLimiter("", 0, client=r, prefix=prefix).check(7)  # 0 = disabled
