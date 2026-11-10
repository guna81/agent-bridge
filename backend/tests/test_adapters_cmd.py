from pathlib import Path

import pytest

from app.adapters.agy import AgyAdapter
from app.adapters.base import NormalizedRequest, RunContext, build_prompt
from app.adapters.claude import DEFAULT_RAW_PROMPT, ClaudeAdapter
from app.adapters.custom import CustomAdapter


def ctx(tmp_path: Path, **kw) -> RunContext:
    base = dict(provider_name="p", mode="raw", auth_mode="api_key", workdir=tmp_path, home=tmp_path / "home",
                binary="/bin/x", raw_system_prompt="RAW PROMPT", api_key=None, max_budget_usd=0.25, extra={})  # fmt: skip
    base.update(kw)
    return RunContext(**base)


def req(system="", text="hi", model="sonnet") -> NormalizedRequest:
    return NormalizedRequest(model=model, system=system, turns=[("user", text)])


def flag(argv, name):
    return argv[argv.index(name) + 1]


# ---- claude ------------------------------------------------------------------------------------
def test_claude_raw_flags(tmp_path):
    cmd = ClaudeAdapter().build_command(req(system="Be terse."), ctx(tmp_path))
    a = cmd.argv
    assert a[:2] == ["/bin/x", "-p"]
    assert flag(a, "--output-format") == "stream-json"
    assert "--verbose" in a and "--include-partial-messages" in a
    assert flag(a, "--tools") == ""  # all built-in tools disabled
    assert "--strict-mcp-config" in a and flag(a, "--mcp-config") == '{"mcpServers":{}}'
    assert flag(a, "--setting-sources") == ""
    assert flag(a, "--max-turns") == "1"
    assert flag(a, "--max-budget-usd") == "0.25"
    assert flag(a, "--model") == "sonnet"
    assert flag(a, "--permission-prompts") == "none"
    assert "--no-session-persistence" in a
    assert "RAW PROMPT" in flag(a, "--system-prompt") and "Be terse." in flag(a, "--system-prompt")
    assert "--append-system-prompt" not in a
    assert cmd.stdin_data == "hi" and "hi" not in a  # prompt over stdin, not argv
    assert cmd.use_pty is False


def test_claude_raw_never_skips_permissions(tmp_path):
    cmd = ClaudeAdapter().build_command(req(), ctx(tmp_path, skip_permissions=True))
    assert "--dangerously-skip-permissions" not in cmd.argv


def test_claude_default_raw_prompt_when_blank(tmp_path):
    cmd = ClaudeAdapter().build_command(req(), ctx(tmp_path, raw_system_prompt=""))
    assert flag(cmd.argv, "--system-prompt") == DEFAULT_RAW_PROMPT


def test_claude_agent_mode(tmp_path):
    c = ctx(tmp_path, mode="agent", skip_permissions=True, extra={"allowed_tools": ["Read", "Bash(git *)"], "max_turns": 5})
    a = ClaudeAdapter().build_command(req(system="ctx"), c).argv
    assert "--tools" not in a and "--strict-mcp-config" not in a
    assert flag(a, "--append-system-prompt") == "ctx" and "--system-prompt" not in a
    assert flag(a, "--allowedTools") == "Read,Bash(git *)"
    assert flag(a, "--max-turns") == "5"
    assert "--dangerously-skip-permissions" in a  # explicit opt-in only


def test_claude_env_isolation_and_key(tmp_path):
    env = ClaudeAdapter().build_command(req(), ctx(tmp_path, api_key="sk-ant-x")).env
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-x"
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "home" / ".claude")
    env = ClaudeAdapter().build_command(req(), ctx(tmp_path, auth_mode="oauth_cli", api_key="sk-ant-x")).env
    assert "ANTHROPIC_API_KEY" not in env  # oauth mode never injects the key
    env = ClaudeAdapter().build_command(req(), ctx(tmp_path, use_host_home=True)).env
    assert "CLAUDE_CONFIG_DIR" not in env


# ---- agy ---------------------------------------------------------------------------------------
def test_agy_raw_command_and_workdir(tmp_path):
    a = AgyAdapter()
    c = ctx(tmp_path, api_key="g-key")
    r = req(system="Talk like a pirate.", model="gemini-3.8-flash-low")
    a.prepare_workdir(r, c)
    agents = (tmp_path / "AGENTS.md").read_text()
    assert "RAW PROMPT" in agents and "Talk like a pirate." in agents
    cmd = a.build_command(r, c)
    assert cmd.argv[:3] == ["/bin/x", "-p", "hi"]
    assert flag(cmd.argv, "--output-format") == "stream-json"
    # agy 1.5: "--mode plan has no effect while slash command expansion is disabled", so raw mode uses the sandbox
    assert "--mode" not in cmd.argv and "--sandbox" in cmd.argv and "--disable-slash-commands" in cmd.argv
    assert flag(cmd.argv, "--model") == "gemini-3.8-flash-low"
    assert "--dangerously-skip-permissions" not in cmd.argv
    assert cmd.use_pty is True  # PTY by default
    assert cmd.env["GEMINI_API_KEY"] == "g-key" and cmd.env["ANTIGRAVITY_API_KEY"] == "g-key"


def test_agy_agent_mode_skip_permissions_opt_in(tmp_path):
    a = AgyAdapter()
    off = a.build_command(req(), ctx(tmp_path, mode="agent")).argv
    on = a.build_command(req(), ctx(tmp_path, mode="agent", skip_permissions=True)).argv
    assert "--dangerously-skip-permissions" not in off and "--dangerously-skip-permissions" in on
    assert flag(off, "--mode") == "accept-edits"


def test_agy_pty_can_be_disabled(tmp_path):
    assert AgyAdapter().build_command(req(), ctx(tmp_path, extra={"use_pty": False})).use_pty is False


# ---- custom ------------------------------------------------------------------------------------
def test_custom_template_placeholders(tmp_path):
    c = ctx(tmp_path, extra={"args_template": ["run", "--m", "{model}", "{prompt}"], "output_format": "text"})
    cmd = CustomAdapter().build_command(req(text="what?", model="m1"), c)
    assert cmd.argv == ["/bin/x", "run", "--m", "m1", "what?"]
    cmd = CustomAdapter().build_command(req(text="what?"), ctx(tmp_path, extra={"args_template": "--x {model}", "stdin": True}))
    assert cmd.argv[1:] == ["--x", "sonnet"] and cmd.stdin_data == "what?"


# ---- prompt building ---------------------------------------------------------------------------
def test_build_prompt_single_turn_is_verbatim():
    assert build_prompt([("user", "hello")]) == "hello"


def test_build_prompt_multi_turn_transcript():
    p = build_prompt([("user", "a"), ("assistant", "b"), ("user", "c")])
    assert p.index("[user]\na") < p.index("[assistant]\nb") < p.rindex("[user]\nc")
