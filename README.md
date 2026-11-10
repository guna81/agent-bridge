# LLM CLI Gateway

Turn the coding CLIs you already have (Claude Code, OpenAI Codex, Google Antigravity, Gemini CLI, or any custom
CLI) into a **self-hosted, OpenAI-compatible and Anthropic-compatible API**, with per-user API keys, a credit
ledger, per-key limits and a web UI.

```
client (OpenAI SDK / Anthropic SDK / curl)
   │  POST /v1/chat/completions   POST /v1/messages
   ▼
auth · key limits · rate limit · queue ──► adapter ──► claude -p … | codex exec … | agy -p … | gemini -p … | custom CLI
   │                                         (own temp dir, minimal env, own process group)
   └─► ledger (credits) ◄── usage parsed from the CLI's output
```

Each request runs the CLI as a non-interactive subprocess in a throwaway directory, the answer is streamed back,
and the cost is charged to the caller's credits.

> **Subscription logins are for personal use only.** Anthropic's terms restrict consumer-subscription OAuth tokens
> to Claude Code and Claude.ai, and say products serving other users should use API keys. Check the terms of the
> other CLIs yourself. Providers therefore default to `api_key` auth. The `oauth_cli` mode (and reusing the
> server user's own CLI login) only works with `PROXY_SINGLE_USER_PERSONAL_USE=true`, which is meant for one
> person running the proxy for themselves on their own machine.

## What is it for?

| Use case | How |
|---|---|
| **Use your own tools with the CLIs you have.** Point any OpenAI/Anthropic SDK, editor plugin or script at one local URL. | Run the proxy on your machine, enable a provider, create a key, set `base_url` to `http://127.0.0.1:8000/v1`. |
| **Share one provider API key with a team, safely.** Give each person or service their own key instead of the real one. | Add users, top up credits, issue keys with a budget, expiry and model allow-list. Revoke one key without touching the rest. |
| **Meter and cap spend.** See who spent what, and stop runaway scripts. | Credit ledger, daily usage chart, per-key `budget_usd`, rate limit, Prometheus `/metrics`. |
| **One API in front of many models.** Switch between Claude, Codex and Gemini by changing the `model` string. | Model ids are `provider/model`, e.g. `claude/haiku`, `codex/default`. Both API dialects work with every provider. |
| **Run agents behind an API.** Let a CLI work on a real project directory, or run your own agent loop with `tools`. | Agent mode with `workdir`, function calling on every provider. See [Running custom agents](#running-custom-agents). |
| **Wrap any command-line program as an API.** | Register it as a custom CLI in the UI. |

## Features

- **Two API dialects**: `/v1/chat/completions` (OpenAI) and `/v1/messages` (Anthropic), both with streaming.
- **Providers**: `claude`, `codex`, `agy`, `gemini`, plus any binary you describe in the UI. A direct-API backend
  bypasses the CLI for Claude and Gemini models.
- **Function calling** (`tools`) on every provider, and **image input** on Claude and Codex.
- **Users, credits and keys**: hashed keys, per-key spending cap, expiry and model allow-list.
- **Raw or agent mode** per provider; agent mode can be pinned to a project directory.
- **Operations**: Prometheus `/metrics`, usage dashboard, SQLite or Postgres, optional Redis for multi-instance
  queueing and rate limiting.

## Quick start (local)

**You need:** macOS or Linux, [`uv`](https://docs.astral.sh/uv/) (it installs Python 3.12 for you), Node 20+, and at
least one CLI on your `PATH` that you have signed in to or have an API key for (`claude`, `codex`, `agy`, `gemini`).

```bash
# 1. Get the code
git clone https://github.com/guna81/llm-cli-gateway.git
cd llm-cli-gateway

# 2. Configure
cp .env.example backend/.env          # the server reads backend/.env
cd backend
uv sync --python 3.12
uv run python -m app.security          # prints a Fernet key
#    → paste it into backend/.env as PROXY_SECRET_KEY=...
#    → also set PROXY_KEY_PEPPER to a long random string, and PROXY_ADMIN_TOKEN (or leave blank to auto-generate)
#    → using your own logged-in CLIs on your own machine? set PROXY_SINGLE_USER_PERSONAL_USE=true

# 3. Build the web UI
(cd ../frontend && npm install && npm run build)

# 4. Run (loads backend/.env automatically)
uv run python run.py                   # http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and sign in with the admin token (`PROXY_ADMIN_TOKEN`, or the generated
`backend/data/admin_token`). UI dev server with hot reload: `cd frontend && npm run dev` (proxies to :8000).

**Then, in the UI (about two minutes):**

1. **Providers** → switch on a provider, then press **Run test**. Test runs are logged but not charged.
2. **Keys & usage** → add a user, add credits, create a key (shown once).
3. **Playground** → chat with it, or open **Quick start** for copy-paste client code.

And from your own code:

```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="sk-proxy-…")   # key from the Keys page
print(c.chat.completions.create(model="claude/haiku", messages=[{"role": "user", "content": "hi"}]).choices[0].message.content)
```

**Not working?** `GET /healthz` should return 200. A provider card showing "not installed" means the binary is not on
the server's `PATH`; "not signed in" means that CLI has no login or API key for the server user. See
[docs/cli-notes.md](docs/cli-notes.md) for each CLI's quirks.

### Running as an Always-On Background Service

To keep the gateway continuously running in the background across reboots and crashes (without keeping a terminal window open):

- **macOS & Linux**:
  ```bash
  ./manage-service.sh install    # registers LaunchAgent (macOS) or systemd user service (Linux)
  ./manage-service.sh status     # verify health and port listening
  ./manage-service.sh logs       # follow live logs
  ./manage-service.sh restart    # restart daemon
  ./manage-service.sh stop       # stop service
  ./manage-service.sh uninstall  # remove service configuration
  ```
- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 install
  powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 status
  powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 logs
  ```
  *(Or run within WSL2 using `./manage-service.sh install`)*
- **Universal (Docker / PM2)**:
  - Docker Compose: `docker compose up -d` (uses `restart: unless-stopped`)
  - PM2: `pm2 start ecosystem.config.cjs && pm2 save && pm2 startup`

See the detailed **[Always-Running Service Guide](docs/always-running.md)** for architecture details, platform specifics, and troubleshooting.

### Docker

```bash
cp .env.example .env     # set PROXY_SECRET_KEY, PROXY_KEY_PEPPER (and PROXY_ADMIN_TOKEN)
docker compose up --build        # published on 127.0.0.1:8000 only
```

The image installs Claude Code from npm. Add other npm-distributed CLIs with
`EXTRA_NPM_CLIS='@openai/codex @google/gemini-cli' docker compose build`. agy has no install channel we could
verify for Linux, so pass its install command from Google's docs as `AGY_INSTALL_CMD='…'`. See
`docs/reverse-proxy.md` before exposing the server.

## Setting up

1. **Providers** → switch on the ones you want, pick the default model and mode.
2. Sign-in, one of:
   - **API key** (default): paste the provider's key in the card. It is Fernet-encrypted at rest and injected only
     for that run (`ANTHROPIC_API_KEY`, `CODEX_API_KEY`/`OPENAI_API_KEY`, `GEMINI_API_KEY`).
   - **CLI login** (needs `PROXY_SINGLE_USER_PERSONAL_USE=true`): tick *Reuse this machine's existing CLI login*, or
     click **Connect account** to run the CLI's login in a terminal on the server and finish it in your browser.
3. Open the card and press **Run test**. Test runs are logged but not charged.
4. **Keys & usage** → add a user, add credits, create a key (shown once; stored hashed).
5. **Playground** → chat with any enabled model, or see **Quick start** in the UI for copy-paste client code.

Custom CLIs: *Add custom CLI* → program path, arguments (`{prompt}`, `{model}`, `{system}`), output format
`text|json|ndjson` and a JSONPath to the answer.

## API

Model ids are `provider/model` (`GET /v1/models` lists what the key may use).

```bash
export KEY=sk-proxy-…   # from the Keys page

# OpenAI dialect
curl -s 127.0.0.1:8000/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d '{
  "model": "claude/haiku",
  "messages": [{"role":"system","content":"Be terse."},{"role":"user","content":"Name a prime number."}]
}'

# Anthropic dialect (works with every provider, not only Claude)
curl -s 127.0.0.1:8000/v1/messages -H "x-api-key: $KEY" -H 'Content-Type: application/json' -d '{
  "model": "codex/default", "max_tokens": 256,
  "messages": [{"role":"user","content":"Name a prime number."}]
}'

curl -s 127.0.0.1:8000/v1/me -H "Authorization: Bearer $KEY"        # credits, usage, key budget
```

```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="sk-proxy-…")
print(c.chat.completions.create(model="claude/haiku", messages=[{"role": "user", "content": "hi"}]).choices[0].message.content)

import anthropic
a = anthropic.Anthropic(base_url="http://127.0.0.1:8000", api_key="sk-proxy-…")
print(a.messages.create(model="claude/haiku", max_tokens=256, messages=[{"role": "user", "content": "hi"}]).content[0].text)
```

Things to know:

- **Stateless.** `messages` becomes a system prompt plus a transcript; nothing is remembered between requests.
- **Function calling is emulated.** The CLIs have no input for caller-defined functions, so the schemas go into
  the system prompt and the model answers with `<tool_call>` blocks that the proxy turns into `tool_calls`
  (OpenAI) or `tool_use` blocks (Anthropic). Replies to requests with `tools` are parsed whole, so they arrive in
  one piece even with `stream: true`, and a model can occasionally ignore the format.
- **Images** must be inline base64 (`data:` URLs, or Anthropic `base64` sources); remote URLs are never fetched.
  Supported by `claude` and `codex` through the CLI, and by the direct-API backend. Other providers return 400.
- `temperature`/`max_tokens` are ignored by the CLIs and listed in the `X-Proxy-Ignored-Params` response header.
- Errors use `{"error": {message,type,code}}` on the OpenAI routes and `{"type":"error","error":{type,message}}`
  on `/v1/messages`. A client disconnect kills the CLI's whole process group.

### Per-key limits

Every key can carry a lifetime spending cap, an expiry and a model allow-list (exact ids or globs):

```bash
curl -s 127.0.0.1:8000/admin/keys -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{
  "user_id": 1, "label": "ci", "budget_usd": 2.0, "expires_in_days": 30, "allowed_models": ["claude/haiku", "codex/*"]
}'
curl -s -X PATCH 127.0.0.1:8000/admin/keys/3 -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d '{"budget_usd": null}'      # null clears a limit; omitted fields are left alone
```

Over budget → `429 key_budget_exhausted`; disallowed model → `403 model_not_allowed`; expired → `401`.

### Admin API

Bearer admin token. `GET|POST /admin/users`, `POST /admin/users/{id}/topup`, `GET|POST /admin/keys`,
`PATCH|DELETE /admin/keys/{id}`, `GET /admin/ledger`, `GET /admin/usage/daily`, `GET|POST|PUT|DELETE /admin/providers…`.
Interactive reference at `/docs`.

## Raw vs agent mode

**Raw** aims for plain assistant replies. How raw it really is depends on the CLI (details in
[`docs/raw-mode.md`](docs/raw-mode.md)): Claude Code's tools and system prompt can be fully replaced; Gemini CLI's
system prompt is replaced; Codex and agy keep their built-in prompt and tools, so instructions are layered on top
and each request carries their prompt overhead (about 8k input tokens for agy, 15–18k for Codex, mostly cached).
The **direct API** backend is the only truly raw path.

**Agent** mode runs the CLI as a full coding agent. Useful settings, under *Advanced settings (JSON)*:

| Key | Effect |
|---|---|
| `workdir` | Run in this existing directory instead of a throwaway temp dir, so an agent can work on a real project across requests. The proxy writes nothing into it. |
| `extra_args` | Extra CLI flags, e.g. `["--agent", "reviewer"]` to select a custom agent defined for that CLI. |
| `max_turns`, `allowed_tools`, `disallowed_tools`, `permission_mode` | Claude Code agent controls. |
| `sandbox` | Codex: `read-only`, `workspace-write` (default) or `danger-full-access`. |

Skipping permission prompts is a separate, explicit opt-in per provider and is never applied in raw mode.

## Running custom agents

- **Your own agent loop** (OpenAI Agents SDK, LangChain, a hand-written loop): point it at `/v1` and pass `tools`.
- **A CLI's own agents**: put the provider in agent mode, set `workdir`, and select the agent with `extra_args`.
- **Any other agent program**: register it as a custom CLI.

## Scaling out

- **Postgres**: `uv sync --extra postgres`, then `PROXY_DATABASE_URL=postgresql+psycopg://user:pass@host/db`.
  Tables are created and upgraded on start.
- **Several instances**: `uv sync --extra redis`, `PROXY_QUEUE_BACKEND=redis`, `PROXY_REDIS_URL=redis://host:6379/0`.
  The concurrency limits and the per-key rate limit are then shared by all instances. Per-user CLI logins live on
  disk (`data/homes`), so use API-key auth, or a shared volume, when running more than one instance.
- **Metrics**: `GET /metrics` in Prometheus text format (requests, tokens, cost, duration, queue). It needs the
  admin token as a Bearer token unless `PROXY_METRICS_PUBLIC=true`.

## Security model

- Each request: fresh temp workdir (deleted after), minimal environment (PATH, HOME, locale and proxy/CA
  variables only), no server secrets, own process group killed on timeout or disconnect.
- Proxy keys are hashed (HMAC-SHA256 with a pepper); provider API keys are Fernet-encrypted; logs are structured
  JSON and omit prompts unless `PROXY_DEBUG_LOG_PROMPTS=true`. The admin token is never put in a URL.
- Global and per-user concurrency, queue timeout, per-key rate limit, request-size and image-size limits. Binds to
  localhost by default.
- Billing: Claude Code reports `total_cost_usd` (used as is). The other CLIs report tokens only, so cost is
  *estimated* from `app/pricing.py` and flagged `estimated` in the ledger. Check that table against current prices.

Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Tests

```bash
cd backend
uv run pytest                          # unit + live-server tests against a scriptable fake CLI (no accounts needed)
RUN_REAL_CLI=1 uv run pytest           # also drives the real installed CLIs (tiny prompts)
REDIS_TEST_URL=redis://127.0.0.1:6379/0 uv run pytest -k redis      # Redis tests against a real server
uv run python scripts/smoke_test.py    # one real prompt through each installed CLI → PASS/FAIL (uses your host logins)
```

Layout: `backend/app/adapters/` (one file per CLI + `registry.py`), `runner/` (subprocess, PTY, queue), `api/`
(`openai.py`, `anthropic.py`, `admin.py`), `toolcall.py`, `service.py`; `docs/cli-notes.md` has the real `--help`
output and findings for each CLI.

## Adding a CLI

Create `backend/app/adapters/mycli.py` implementing `CliAdapter` (`build_command`, `prepare_workdir`, `parse_line`,
`login_command`, `auth_status`), add it to `ADAPTERS` in `registry.py`, and add a flavor to `tests/fake_cli.py`.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
