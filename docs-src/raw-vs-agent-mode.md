# Raw vs agent mode

## Raw mode

**Raw** asks a coding-agent CLI to behave like a plain chat model: answer the question, don't use tools, don't introduce itself as a coding agent. It is *steering plus tool removal*, not a different model API. How raw it really is depends on the CLI.

| | Claude Code | Codex | Gemini CLI | Antigravity (`agy`) |
|---|---|---|---|---|
| System prompt | **Replaced** | Built-in kept; instructions layered on top via `AGENTS.md` | **Replaced** | Built-in kept; instructions layered on top via `AGENTS.md` |
| Built-in tools | **Removed** | Not removable; read-only sandbox | Not removable; nothing can approve a tool in headless mode | Not removable |
| Prompt overhead | ~650 input tokens | 15 to 18k (mostly cached) | Not measured | ~8k |

The **Direct API** backend is the only truly raw path.

### What raw mode can't guarantee

1. **Identity.** The model may mention being a coding assistant, especially `agy`.
2. **Token overhead and cost.** CLIs add their own context, and billing reflects it.
3. **Sampling parameters.** `temperature` and `max_tokens` are ignored (see the `X-Proxy-Ignored-Params` header).
4. **Latency.** A process starts per request (about 2 to 3 s for Claude, 10 to 15 s for `agy`).
5. **Tool use by `agy`.** Its tools can't be removed; treat its raw mode as best effort.
6. **Format fidelity.** `n>1`, logprobs and JSON mode aren't supported; `response_format` is ignored.

Skipping permission prompts is **never** applied in raw mode.

### Direct API backend

Set a provider's *Backend* to **Direct API** and store an API key. Requests go straight to Anthropic's Messages API (`claude`) or Google's Gemini API (`agy`) over HTTPS: no subprocess, no agent harness, no hidden prompt, native `temperature`/`max_tokens`, true streaming and exact token counts.

Overrides: `extra.base_url` for hosts and `extra.direct_model_map` for model IDs (for example `{"sonnet": "claude-sonnet-5-5"}`).

!!! note
    The direct backends are tested against a mock transport only; they haven't been run against the live APIs.

## Agent mode

**Agent** mode runs the CLI as a full coding agent.

!!! danger
    Agent mode can run commands and edit files **as the server user**. Enable it only for trusted callers.

Settings under *Advanced settings (JSON)*:

| Key | Effect |
|---|---|
| `workdir` | Run in this existing directory instead of a throwaway temp dir, so an agent can work on a real project across requests. The gateway writes nothing into it. |
| `extra_args` | Extra CLI flags, e.g. `["--agent", "reviewer"]` to pick a custom agent defined for that CLI. |
| `max_turns`, `allowed_tools`, `disallowed_tools`, `permission_mode` | Claude Code agent controls. |
| `sandbox` | Codex: `read-only`, `workspace-write` (default) or `danger-full-access`. |

Skipping permission prompts is a separate, explicit opt-in per provider.
