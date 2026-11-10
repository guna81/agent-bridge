import json

from app.adapters.agy import AgyAdapter
from app.adapters.base import Done, Error, TextDelta, ToolEvent, Usage
from app.adapters.claude import ClaudeAdapter
from app.adapters.custom import CustomAdapter

from .conftest import FIXTURES


def feed(adapter, lines):
    out = []
    for ln in lines:
        out += adapter.parse_line(ln)
    return out


def test_claude_real_capture():
    """Parses the real stream-json capture from claude 2.1.310 (raw-mode invocation)."""
    lines = (FIXTURES / "claude_raw_stream.ndjson").read_text().splitlines()
    evs = feed(ClaudeAdapter(), lines)
    text = "".join(e.text for e in evs if isinstance(e, TextDelta))
    assert text == "Hello there, friend!"  # partial deltas only: the whole `assistant` message is not double-counted
    usage = [e for e in evs if isinstance(e, Usage)]
    assert len(usage) == 1
    assert usage[0].input_tokens == 692 and usage[0].output_tokens == 10  # 2 + 690 cache-creation
    assert usage[0].cost_usd and usage[0].cost_usd > 0
    assert isinstance(evs[-1], Done) and evs[-1].finish_reason == "stop"
    assert any(isinstance(e, ToolEvent) for e in evs)  # system/init noise is classified, not leaked as text


def test_claude_assistant_message_used_when_no_partials():
    a = ClaudeAdapter()
    evs = a.parse_line(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "whole"}]}}))
    assert [e.text for e in evs if isinstance(e, TextDelta)] == ["whole"]


def test_claude_tool_use_is_not_text():
    a = ClaudeAdapter()
    evs = a.parse_line(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}))
    assert len(evs) == 1 and isinstance(evs[0], ToolEvent) and evs[0].name == "Bash"


def test_claude_error_result():
    evs = ClaudeAdapter().parse_line(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                                                  "result": "Exceeded USD budget (0.1)", "usage": {}}))  # fmt: skip
    err = [e for e in evs if isinstance(e, Error)]
    assert err and err[0].code == "budget_exceeded"


def test_claude_ignores_garbage_lines():
    a = ClaudeAdapter()
    assert a.parse_line("Warning: no stdin data received in 3s") == []
    assert a.parse_line("{not json") == []


def test_agy_real_capture():
    lines = (FIXTURES / "agy_stream.ndjson").read_text().splitlines()
    evs = feed(AgyAdapter(), lines)
    assert "".join(e.text for e in evs if isinstance(e, TextDelta)) == "pong\n"
    u = [e for e in evs if isinstance(e, Usage)][0]
    assert u.input_tokens > 0 and u.output_tokens > 0 and u.cost_usd is None  # agy reports tokens, not dollars
    assert isinstance(evs[-1], Done)


def test_agy_json_format_single_object():
    o = {"conversation_id": "x", "status": "SUCCESS", "response": "pong\n", "usage": {"input_tokens": 5, "output_tokens": 2}}
    evs = feed(AgyAdapter(), [json.dumps(o)])
    assert [e.text for e in evs if isinstance(e, TextDelta)] == ["pong\n"]


def test_agy_pty_noise_is_ignored():
    evs = AgyAdapter().parse_line('\x1b[?25l{"event":"init","init":{}}\r')
    assert evs == [] or isinstance(evs[0], ToolEvent)  # ANSI-prefixed junk must not crash


def test_agy_failure_status():
    evs = AgyAdapter().parse_line(json.dumps({"event": "result", "result": {"status": "ERROR", "error": "quota"}}))
    assert isinstance(evs[0], Error) and "quota" in evs[0].message


def _custom(fmt, path=None):
    from pathlib import Path

    from app.adapters.base import NormalizedRequest, RunContext

    a = CustomAdapter()
    ctx = RunContext("c", "raw", "api_key", Path("."), Path("."), "/bin/x", "", extra={"output_format": fmt, "json_path": path})
    a.build_command(NormalizedRequest("m", "", [("user", "q")]), ctx)
    return a


def test_custom_text_preserves_lines_without_trailing_newline():
    a = _custom("text")
    evs = feed(a, ["one", "two"]) + a.finish()
    assert "".join(e.text for e in evs if isinstance(e, TextDelta)) == "one\ntwo"


def test_custom_json_path():
    a = _custom("json", "$.data.answer.text")
    evs = feed(a, ['{"data":', '{"answer": {"text": "hi"}}}']) + a.finish()
    assert "".join(e.text for e in evs if isinstance(e, TextDelta)) == "hi"


def test_custom_ndjson_path_and_bad_json():
    a = _custom("ndjson", "$.delta.text")
    evs = feed(a, ['{"type":"chunk","delta":{"text":"a"}}', "junk", '{"type":"chunk","delta":{"text":"b"}}', '{"type":"done"}']) + a.finish()
    assert "".join(e.text for e in evs if isinstance(e, TextDelta)) == "ab"


def test_custom_json_path_matching_nothing_is_an_error():
    b = _custom("json", "$.nope")
    feed(b, ['{"x":1}'])
    assert any(isinstance(e, Error) for e in b.finish())
