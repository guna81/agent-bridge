# Providers

A provider is an agent CLI or API that the gateway can route requests to.

## Supported providers

| Provider | CLI | Notes |
|---|---|---|
| Claude Code | `claude` | Supports raw and agent mode, images, direct API backend |
| Codex | `codex` | Images supported; models auto-discovered |
| Antigravity | `agy` | Direct API backend uses Gemini API |
| Gemini CLI | `gemini` | |
| Custom CLI | any | Add your own program |
| Direct API | n/a | Talks to the provider's HTTPS API, no subprocess |

A provider card showing **not installed** means the binary isn't on the server's `PATH`. **Not signed in** means the CLI has no login or API key for the server user.

## Set up a provider

1. In **Providers**, switch the provider on and choose its default model and mode.
2. Choose a sign-in method:
    - **API key** (default for separately configured servers): paste the key. It's Fernet-encrypted at rest and injected only for that run (`ANTHROPIC_API_KEY`, `CODEX_API_KEY`/`OPENAI_API_KEY`, `GEMINI_API_KEY`).
    - **CLI login:** tick *Reuse this machine's existing CLI login*, or click **Connect account** to run the CLI login in a terminal on the server and finish in your browser.
3. Press **Run test**. Test runs are logged but not charged.

!!! warning
    For separately configured servers, `oauth_cli` and reuse of the server user's CLI login require `PROXY_SINGLE_USER_PERSONAL_USE=true`. Keep it `false` for anything other people use.

## Custom CLIs

Choose **Add custom CLI** and set:

- the program path;
- arguments, using `{prompt}`, `{model}` and `{system}` placeholders;
- the output format: `text`, `json` or `ndjson`;
- a JSONPath to the answer (for JSON formats).

To run your own agent program, register it as a custom CLI.

## Fallback model

A provider can name `extra.fallback_model` (also editable on the Providers page) as a `provider/model` ID. The fallback is used only **before work starts**, and only when the primary is disabled, its CLI binary is missing or its direct API key is missing. Both models must be allowed by the key. There is no retry after a request starts, since it may already have incurred charges.

Responses include `X-Proxy-Model`; a fallback also adds `X-Proxy-Requested-Model`.

## Pricing

Claude Code reports its own cost, which is used as is. Other CLIs report tokens only, so cost is **estimated** from a built-in price table and flagged `estimated` in the ledger. For aliases or models the table doesn't cover, set `extra.pricing_rates` to a map such as `{"actual-model-id": [3.0, 15.0]}` (input and output USD per million tokens). The Providers page has a pricing editor. CLI aliases such as `default` can't identify the underlying model, so set their rates explicitly.

## Agent settings

Under *Advanced settings (JSON)* you can set `workdir`, `extra_args`, `sandbox` and more. See [Raw vs agent mode](raw-vs-agent-mode.md).
