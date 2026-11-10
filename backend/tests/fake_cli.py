#!/usr/bin/env python3
"""Scriptable stand-in for `claude` / `agy` / a generic CLI. Output shapes mirror the real captures in tests/fixtures.

Invoked through tiny wrapper scripts (see conftest.make_wrapper) as:
  fake_cli.py --flavor=<claude|agy|codex|gemini|text|ndjson|json> ARGS...

Prompt-triggered behaviours:
  FAKE_SLEEP        hang for 60s without output          FAKE_ERROR   report an error result
  FAKE_CRASH        exit 3 with a stderr message         FAKE_SLOW    stream words 0.3s apart
  FAKE_PIDFILE=path write our pid to `path` first        FAKE_WHOAMI  answer depends on the system prompt
  FAKE_TOOLCALL     answer with a <tool_call> block      FAKE_IMAGES  answer "IMAGES=<n received>"
  FAKE_ARGV         answer with our own argv (JSON)
"""
import json
import os
import re
import sys
import time

args = sys.argv[1:]
flavor = "text"
if args and args[0].startswith("--flavor="):
    flavor = args.pop(0).split("=", 1)[1]


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


model = opt("--model", "fake-model")
fmt = opt("--output-format", "text")
system = ""
n_images = 0
if flavor == "claude":
    prompt = sys.stdin.read()
    system = opt("--system-prompt", "") or opt("--append-system-prompt", "")
    if opt("--input-format") == "stream-json":  # image requests: one user message with content blocks
        blocks = json.loads(prompt.splitlines()[0])["message"]["content"]
        n_images = sum(1 for b in blocks if b["type"] == "image")
        prompt = "".join(b["text"] for b in blocks if b["type"] == "text")
elif flavor == "codex":
    assert args[:2] == ["exec", "--json"] and args[-1] == "-", args
    prompt = sys.stdin.read()
    agents = os.path.join(os.getcwd(), "AGENTS.md")
    system = open(agents).read() if os.path.exists(agents) else ""
    n_images = sum(1 for i, a in enumerate(args) if a == "-i" and os.path.exists(args[i + 1]))
    model = opt("-m", "codex-default")
elif flavor == "gemini":
    prompt = opt("-p", "")
    sysfile = os.environ.get("GEMINI_SYSTEM_MD", "")
    system = open(sysfile).read() if sysfile and os.path.exists(sysfile) else ""
    model = opt("-m", "gemini-default")
elif flavor == "agy":
    prompt = opt("-p", "") or opt("--print", "")
    agents = os.path.join(os.getcwd(), "AGENTS.md")
    system = open(agents).read() if os.path.exists(agents) else ""
else:
    prompt = opt("--prompt", "") or (args[-1] if args else "")
    if not sys.stdin.isatty():
        piped = sys.stdin.read()
        prompt = piped or prompt

m = re.search(r"FAKE_PIDFILE=(\S+)", prompt)
if m:
    open(m.group(1), "w").write(str(os.getpid()))
sys.stdout.reconfigure(line_buffering=True)


def emit(o):
    print(json.dumps(o), flush=True)


if "FAKE_CRASH" in prompt:
    print("fake: boom", file=sys.stderr)
    sys.exit(3)
if "FAKE_SLEEP" in prompt:
    time.sleep(60)

last = [l for l in prompt.strip().splitlines() if l.strip() and not l.startswith("[")][-1:] or [""]
if "FAKE_WHOAMI" in prompt:
    answer = ("I am a helpful assistant." if "Do not mention being a coding agent" in system
              else "I am a coding agent that can edit files.")
elif "FAKE_TOOLCALL" in prompt and "<tool_result" not in prompt:
    answer = 'Let me check.\n<tool_call>{"name": "get_weather", "arguments": {"city": "Paris"}}</tool_call>'
elif "FAKE_IMAGES" in prompt:
    answer = f"IMAGES={n_images}"
elif "FAKE_ARGV" in prompt:
    answer = "ARGV=" + json.dumps(args)
elif "FAKE_SYSTEM" in prompt:
    answer = "SYSTEM=" + json.dumps(system)
else:
    answer = f"FAKE[{model}][sys={'yes' if system else 'no'}] {last[0]}"
words = re.findall(r"\S+\s*", answer)
delay = 0.3 if "FAKE_SLOW" in prompt else 0.0
in_tok, out_tok = max(1, len(prompt) // 4), len(words)

if flavor == "claude":
    sid = "fake-session"
    emit({"type": "system", "subtype": "init", "session_id": sid, "tools": [], "mcp_servers": [], "model": model})
    err = "FAKE_ERROR" in prompt or "FAKE_MIDERROR" in prompt
    if "FAKE_ERROR" not in prompt:  # FAKE_ERROR fails before producing any text
        emit({"type": "stream_event", "event": {"type": "message_start", "message": {}}})
        emit({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}})
        for w in words:
            time.sleep(delay)
            emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": w}}})
        emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]}})
        emit({"type": "stream_event", "event": {"type": "message_stop"}})
    emit({"type": "result", "subtype": "error_during_execution" if err else "success", "is_error": err,
          "result": "fake failure" if err else answer, "stop_reason": "end_turn", "session_id": sid,
          "total_cost_usd": 0.0123, "usage": {"input_tokens": in_tok, "output_tokens": out_tok,
                                              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}})
elif flavor == "agy":
    if "FAKE_ERROR" in prompt:
        emit({"event": "result", "result": {"status": "ERROR", "response": "", "error": "fake agy failure"}})
        sys.exit(0)
    usage = {"input_tokens": in_tok, "output_tokens": out_tok, "thinking_tokens": 0, "cache_read_tokens": 0, "total_tokens": in_tok + out_tok}
    if fmt == "text":
        print(answer)
    elif fmt == "json":
        emit({"conversation_id": "c1", "status": "SUCCESS", "response": answer + "\n", "usage": usage})
    else:
        emit({"event": "init", "conversation_id": "c1", "init": {"model": model, "tools": ["run_command"]}})
        emit({"event": "step_update", "step_update": {"step_index": 0, "state": "DONE", "step_type": "user_input"}})
        for w in words:
            time.sleep(delay)
            emit({"event": "step_update", "step_update": {"step_index": 1, "state": "ACTIVE", "step_type": "agent_response", "text_delta": w}})
        emit({"event": "step_update", "step_update": {"step_index": 1, "state": "DONE", "step_type": "agent_response", "text_delta": "\n"}})
        emit({"event": "result", "result": {"conversation_id": "c1", "status": "SUCCESS", "response": answer + "\n", "usage": usage}})
elif flavor == "codex":
    emit({"type": "thread.started", "thread_id": "t1"})
    emit({"type": "turn.started"})
    if "FAKE_ERROR" in prompt:
        emit({"type": "turn.failed", "error": {"message": "fake codex failure"}})
        sys.exit(1)
    emit({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": answer}})
    emit({"type": "turn.completed", "usage": {"input_tokens": in_tok, "cached_input_tokens": 0, "output_tokens": out_tok, "reasoning_output_tokens": 0}})
elif flavor == "gemini":
    emit({"type": "init", "session_id": "s1", "model": model})
    emit({"type": "message", "role": "user", "content": prompt})
    if "FAKE_ERROR" in prompt:
        emit({"type": "result", "status": "error", "error": {"message": "fake gemini failure"}})
        sys.exit(1)
    for w in words:
        time.sleep(delay)
        emit({"type": "message", "role": "assistant", "content": w, "delta": True})
    emit({"type": "result", "status": "success", "stats": {"total_tokens": in_tok + out_tok, "input_tokens": in_tok, "output_tokens": out_tok}})
elif flavor == "ndjson":
    for w in words:
        time.sleep(delay)
        emit({"type": "chunk", "delta": {"text": w}})
    emit({"type": "done"})
elif flavor == "json":
    emit({"data": {"answer": {"text": answer}}})
else:  # text
    for ln in (answer + "\nsecond line").splitlines():
        time.sleep(delay)
        print(ln)
