"""'who are you?' in raw mode.

The fake-CLI variant is a hard assertion about OUR pipeline (raw mode applies the raw system prompt; agent mode doesn't).
The real-CLI variant is best effort and only warns: raw mode steers the model, it cannot guarantee anything
(see docs/raw-mode.md).
"""
import os
import re
import shutil
import warnings

import pytest
from openai import OpenAI

from app.config import get_settings

CODING_AGENT = re.compile(r"coding (agent|assistant)|software engineer|claude code|antigravity|command[- ]line (tool|interface)", re.I)
Q = [{"role": "user", "content": "FAKE_WHOAMI who are you?"}]


def ask(live, model):
    return OpenAI(base_url=live.v1, api_key=live.key, max_retries=0, timeout=180).chat.completions.create(model=model, messages=Q).choices[0].message.content


@pytest.mark.parametrize("model", ["claude/sonnet", "agy/gemini-3.8-flash-low"])
def test_raw_mode_applies_the_raw_prompt_so_fake_reply_is_not_a_coding_agent(live, model):
    live.admin("PUT", f"/providers/{model.split('/')[0]}", json={"mode": "raw", "raw_system_prompt": "You are a helpful assistant. Answer directly. Do not mention being a coding agent. Do not use tools."})
    assert not CODING_AGENT.search(ask(live, model))


def test_agent_mode_does_not_apply_the_raw_prompt(live):
    live.admin("PUT", "/providers/claude", json={"mode": "agent"})
    try:
        assert CODING_AGENT.search(ask(live, "claude/sonnet"))
    finally:
        live.admin("PUT", "/providers/claude", json={"mode": "raw"})


def test_custom_raw_prompt_is_used(live):
    live.admin("PUT", "/providers/claude", json={"raw_system_prompt": "Reply in French. Do not mention being a coding agent."})
    try:
        assert "[sys=yes]" in OpenAI(base_url=live.v1, api_key=live.key).chat.completions.create(model="claude/sonnet", messages=[{"role": "user", "content": "x"}]).choices[0].message.content
    finally:
        live.admin("PUT", "/providers/claude", json={"raw_system_prompt": "You are a helpful assistant. Answer directly. Do not mention being a coding agent. Do not use tools."})


@pytest.mark.real
@pytest.mark.skipif(os.environ.get("RUN_REAL_CLI") != "1", reason="set RUN_REAL_CLI=1")
@pytest.mark.parametrize("cli,model", [("claude", "haiku"), ("agy", "gemini-3.8-flash-low")])
def test_real_cli_raw_identity_best_effort(live, monkeypatch, cli, model):
    if not shutil.which(cli):
        pytest.skip(f"{cli} not installed")
    monkeypatch.setattr(get_settings(), "single_user_personal_use", True)
    name = f"raw{cli}"
    live.admin("POST", "/providers", json={"name": name, "kind": cli, "enabled": True, "binary_path": shutil.which(cli), "auth_mode": "oauth_cli",
                                           "use_host_home": True, "mode": "raw", "default_model": model, "models": [model]})  # fmt: skip
    reply = OpenAI(base_url=live.v1, api_key=live.key, timeout=180).chat.completions.create(
        model=f"{name}/{model}", messages=[{"role": "user", "content": "who are you? one short sentence."}]).choices[0].message.content
    print(f"\n[{cli}] raw-mode reply: {reply!r}")
    if CODING_AGENT.search(reply):
        warnings.warn(f"{cli} raw mode still described itself as a coding agent: {reply!r}", stacklevel=1)
    assert reply.strip()  # we only insist that a real answer came back
