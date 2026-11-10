# Raw mode: what it does, what it cannot guarantee

"Raw" mode asks a coding-agent CLI to behave like a plain chat model: answer the question, don't use tools, don't
introduce itself as a coding agent. **It is steering plus tool removal, not a different model API.**
The only truly raw path is the *direct API* backend (below).

## What each CLI does in raw mode

| | `claude` | `agy` |
|---|---|---|
| System prompt | **Replaced** (`--system-prompt`) with the provider's raw prompt + any `system` messages from the request | **Cannot be replaced.** No flag exists; `.antigravity/system_instructions.md` is ignored (tested). We write `<workdir>/AGENTS.md`, which agy injects *on top of* its built-in prompt |
| Built-in tools | **Removed**: `--tools ""`. Verified: the stream's `init` event reports `"tools": []` | **Not removable.** No flag. `init` still lists ~60 tools (browser, run_command, write_to_file…). We pass `--sandbox` and a fresh empty temp workdir, but the model can still *try* to use tools. (`--mode plan` is not used: agy 1.5 reports that it has no effect together with `--disable-slash-commands`, which we keep so a caller's prompt is never expanded as a slash command) |
| MCP | `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`; init reports `"mcp_servers": []` | Fresh isolated HOME has none configured; not otherwise controllable per request |
| User/project settings & CLAUDE.md | `--setting-sources ""` plus an empty cwd | empty cwd; isolated HOME |
| Turns / spend | `--max-turns 1` (hidden flag: works but not in `--help`), `--max-budget-usd`, `--no-session-persistence`, `--permission-prompts none` | `--print-timeout`, process killed on timeout |
| `--dangerously-skip-permissions` | **Never** in raw mode (enforced in adapter *and* rejected by the admin API) | Never in raw mode |
| Output | Only assistant text deltas are forwarded; tool_use / tool_result / system events are dropped | Only `agent_response` text deltas are forwarded |

### Codex and Gemini CLI

| | `codex` | `gemini` |
|---|---|---|
| System prompt | **Cannot be replaced.** No flag. We write `<workdir>/AGENTS.md`, which Codex reads as project instructions on top of its built-in prompt (verified on 0.167.0: a "begin with ZEBRA7" instruction was followed) | **Replaced**: the raw prompt is written to a file and passed as `GEMINI_SYSTEM_MD` (from the docs; not verified against a real binary) |
| Built-in tools | Not removable. `-s read-only` sandbox: commands cannot write or use the network | Not removable. `--approval-mode default`: nothing can approve a tool in headless mode |
| User config | `--ignore-user-config` (no MCP servers or profiles from `~/.codex/config.toml`), `--ephemeral`, `--skip-git-repo-check` | isolated HOME unless the host login is reused |
| Skip-permissions flag | Never in raw mode | Never in raw mode |
| Output | Only `agent_message` items are forwarded | Only assistant `message` events are forwarded |
| Overhead | 15–18k input tokens per request (mostly cached) | not measured |

## What raw mode cannot guarantee

1. **Identity.** The model may still say it is Claude or Gemini (that's true and fine), but may occasionally mention being a coding assistant, especially agy, whose built-in prompt is large and cannot be removed. Observed on this machine: claude replied "I'm Claude, an AI assistant made by Anthropic."; agy replied "I am Gemini, a large language model…" (with the AGENTS.md steer; without it, "I am Antigravity, an AI coding assistant…").
2. **Token overhead / cost.** CLIs add their own context. agy's baseline is ~7.6k input tokens per call; claude ~650 even with tools off. Billing reflects that.
3. **Sampling parameters.** Neither CLI exposes `temperature` or `max_tokens`. They are ignored and reported in the `X-Proxy-Ignored-Params` response header.
4. **Latency.** A process starts per request (claude ≈ 2–3 s, agy ≈ 10–15 s for a one-word answer).
5. **Tool use by agy.** With tools unremovable, a prompt that asks for file or shell work may be attempted inside the empty temp dir (plan mode should prevent edits, but that is the CLI's behaviour, not ours). Treat agy raw mode as best effort.
6. **Format fidelity.** Tool calls, function calling, images, `n>1`, logprobs, JSON mode are not supported. `tools`/`response_format` request fields are ignored.

## The test

`backend/tests/test_raw_identity.py` sends "who are you?":
* against the fake CLI it **asserts** that raw mode applies the raw prompt (and agent mode doesn't);
* with `RUN_REAL_CLI=1` it asks the real CLIs and **warns** (never fails) if the reply describes a coding agent. It's best effort by design.

## Direct API backend (the only truly raw path)

Set a provider's *Backend* to **Direct API** and store an API key. Requests then go straight to
Anthropic's Messages API (`claude`) or Google's Gemini API (`agy`) over HTTPS: no subprocess, no agent harness, no hidden
prompt, native `temperature`/`max_tokens`, true streaming, exact token counts. It has no overhead and no CLI to hijack the answer.
Override hosts with `extra.base_url`, and model-id mapping with `extra.direct_model_map` (e.g. `{"sonnet": "claude-sonnet-5-5"}`). The Gemini mapping for
agy slugs like `gemini-3.8-flash-low` just strips the `-low/-medium/-high` suffix, which is an unverified guess; set the map explicitly.
The direct backends are unit-tested against a mock transport only; they have **not** been run against the live APIs.
