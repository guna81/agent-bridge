<p align="center"><img src="docs/assets/agentbridge-icon.svg" alt="AgentBridge logo" width="96" height="96"></p>

<h1 align="center">AgentBridge</h1>

<p align="center">Track AI agent subscription usage and connect your tools to a local API gateway.</p>
<p align="center"><a href="https://guna81.github.io/agent-bridge/">Website</a> · <a href="https://github.com/guna81/agent-bridge/releases/latest">Latest release</a> · <a href="docs/releases.md">Release guide</a></p>

AgentBridge brings two workflows together: monitor available subscription usage for supported coding agents, and expose configured agent CLIs through OpenAI-compatible and Anthropic-compatible APIs. The CLI runs a local gateway, opens a web dashboard, and can show usage in the macOS menu bar or a Windows or Linux system tray.

## Install

Prebuilt packages include the CLI and dashboard; you do not need to install Python or Node.js.

**macOS (Apple Silicon) and Linux (x86-64):**

```sh
curl -fsSL https://raw.githubusercontent.com/guna81/agent-bridge/main/install.sh | sh
```

**Windows (x86-64, PowerShell):**

```powershell
irm https://raw.githubusercontent.com/guna81/agent-bridge/main/install.ps1 | iex
```

The installers download the [latest release](https://github.com/guna81/agent-bridge/releases/latest) and verify its SHA-256 checksum. On macOS and Linux, ensure `~/.local/bin` is on your `PATH`; on Windows, open a new terminal after installation. Release binaries are unsigned. Supported Linux binaries require glibc and a system at least as recent as Ubuntu 22.04; the tray requires a supported X11 desktop. Windows and Linux packages are built and smoke-tested in CI, but interactive tray and provider login behavior still needs desktop testing.

## Get started

1. Install and sign in to the agent CLIs you want to use, separately from AgentBridge. Usage availability varies by provider and platform.
2. Start AgentBridge and open its signed-in dashboard:

   ```sh
   agentbridge start
   agentbridge dashboard
   ```

3. In **Providers**, review and enable the providers you want. Existing provider settings are not overwritten. In **Subscription usage**, inspect available limits; in **Status indicator**, enable or hide the indicator, choose up to two providers, the display style, and refresh interval.
4. To use the gateway from another app, add a user and create a key under **API keys & users**. Point an OpenAI-compatible client at `http://127.0.0.1:43187/v1` and use a `provider/model` identifier. The **API quick start** and **Playground** pages provide examples.

Provider API keys and personal CLI logins are available: choose the sign-in method separately for each provider in the dashboard. Newly created built-in providers are configured to reuse local CLI logins. The dashboard command opens the app signed in; for manual sign-in use `agentbridge dashboard --show-token` and keep the token private.

> **Subscription logins are for personal use only.** Anthropic's terms restrict consumer-subscription OAuth tokens to Claude Code and Claude.ai. Check the terms of other providers before using their subscription credentials. For separately configured servers, `oauth_cli` and reuse of the server user's CLI login require `PROXY_SINGLE_USER_PERSONAL_USE=true`.

## Everyday commands

```sh
agentbridge status                # gateway health and address
agentbridge autostart status      # check startup at user login
agentbridge autostart enable      # start automatically when you sign in
agentbridge autostart disable     # turn automatic startup off
agentbridge dashboard             # open the signed-in dashboard
agentbridge --version             # installed version
agentbridge update                # install the latest stable release
agentbridge uninstall             # stop and remove the installation; keep user data
agentbridge uninstall --purge     # also remove settings, credentials and database
agentbridge stop                  # stop gateway and indicator
agentbridge start                 # start the gateway
agentbridge start --port 43188    # choose another port
agentbridge start --no-tray       # run without a status indicator
```

After an update, run `agentbridge stop` followed by `agentbridge start` to use the new version. Updates retain the existing installation files and user data. Uninstall retains user data unless `--purge` is supplied; a source checkout and installer launcher backups are retained. On Windows, packaged uninstall completes after the command exits and reports a log path. AgentBridge stores its database, secrets, and logs in `~/.agentbridge` (override with `AGENTBRIDGE_HOME`) and binds to loopback by default. For tray startup errors on Windows or Linux, check `~/.agentbridge/tray.log`. After the first successful start, AgentBridge enables automatic startup at user login when it can verify the installed launcher. It remembers the gateway port. Use `agentbridge autostart disable` to turn this off. Linux requires a desktop session that supports XDG autostart; tray support varies by desktop.

The indicator shows remaining capacity: its bars shrink as usage increases. The compact icon opens the same usage details, and the menu includes percentages and reset times when available. Windows and Linux use compact tray graphics; an always-visible widget is not currently available. See the [status indicator guide](docs/mac-status-bar.md).

## Features

- **Subscription usage**: view available 5-hour and weekly limits and reset times for supported providers.
- **Local API gateway**: OpenAI-compatible `/v1/chat/completions` and Anthropic-compatible `/v1/messages`, including streaming.
- **Providers**: Claude Code, Codex, Antigravity, Gemini CLI, custom CLIs, and supported direct API backends.
- **Access and accounting**: users, hashed API keys, credit ledger, budgets, expiry, and model restrictions.
- **Operations**: request history, usage export, Prometheus metrics, SQLite or PostgreSQL, and optional Redis queues.
- **Agents and tools**: function calling, image input where supported, and optional agent mode.

Requests run provider CLIs as subprocesses and charge applicable gateway usage to the caller's credits. Agent mode can run commands and edit files as the server user; enable it only for trusted callers.

## Roadmap

These are future plans, not available features:

- **Multi-agent orchestration**: a master agent that coordinates and delegates work to other agents, such as Claude and Gemini, and brings their results together.
- **LLM router**: route tasks to an appropriate model based on their complexity, with the aim of balancing capability, speed, and cost.

## Install from source

For development, install Python 3.12 via [uv](https://docs.astral.sh/uv/) and Node.js/npm, then:

```sh
git clone https://github.com/guna81/agent-bridge.git
cd agent-bridge
./install-cli.sh
agentbridge start
agentbridge dashboard
```

On Windows, use `./install-cli.ps1` in PowerShell instead. Follow the printed PATH instructions and keep the checkout in place: the installed command uses its Python environment and built dashboard. `agentbridge update` is for packaged installations; update a source checkout with Git and rebuild it.

## Run the source server directly

This alternative runs the standalone source server on port **8000** by default. It is separate from the packaged CLI, which defaults to port **43187**.

**You need:** macOS or Linux, [`uv`](https://docs.astral.sh/uv/) (it installs Python 3.12 for you), Node 20+, and at
least one CLI on your `PATH` that you have signed in to or have an API key for (`claude`, `codex`, `agy`, `gemini`).

```bash
# 1. Get the code
git clone https://github.com/guna81/agent-bridge.git
cd agent-bridge

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
2. **API keys & users** → add a user, add credits, create a key (shown once).
3. **Playground** → chat with it, or open **API quick start** for copy-paste client code.

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

These optional scripts operate on a source checkout and are separate from `agentbridge start`. They may stop an existing process on the configured port; check the port before using them.

To keep the gateway continuously running in the background across reboots and crashes (without keeping a terminal window open):

- **macOS & Linux**:
  ```bash
  ./manage-service.sh install    # registers LaunchAgent (macOS) or systemd user service (Linux)
  ./manage-service.sh status     # verify health and port listening
  ./manage-service.sh logs       # follow live logs
  ./manage-service.sh restart    # restart daemon
  ./manage-service.sh stop       # stop service
  ./manage-service.sh menubar    # launch native macOS Menu Bar app with live CLI progress bar
  ./manage-service.sh uninstall  # remove service configuration
  ```
- **macOS menu bar helper**:
  ```bash
  ./manage-service.sh menubar start   # starts native Swift menu bar progress bar app
  ./manage-service.sh menubar status  # check menu bar app state
  ./manage-service.sh menubar stop    # stop menu bar app
  ```
  See the **[status indicator guide](docs/mac-status-bar.md)** for available display settings.
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
4. **API keys & users** → add a user, add credits, create a key (shown once; stored hashed).
5. **Playground** → chat with any enabled model, or see **API quick start** in the UI for copy-paste client code.

Custom CLIs: *Add custom CLI* → program path, arguments (`{prompt}`, `{model}`, `{system}`), output format
`text|json|ndjson` and a JSONPath to the answer.

## API

The examples below use port 8000 for the standalone source server. For the packaged CLI, replace it with 43187 or your configured port.

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
  Direct API providers preserve images on earlier user turns. CLI providers accept images only in the final
  user message; earlier images are rejected rather than silently moving them to a different turn.
- `temperature`/`max_tokens` are ignored by the CLIs and listed in the `X-Proxy-Ignored-Params` response header.
- Errors use `{"error": {message,type,code}}` on the OpenAI routes and `{"type":"error","error":{type,message}}`
  on `/v1/messages`. A client disconnect kills the CLI's whole process group.

### Per-key limits

Every key can carry lifetime, daily, and monthly spending budgets, an expiry and a model allow-list (exact ids or globs). Daily and monthly budgets reset at UTC boundaries; outstanding reservations remain counted until settled or released:

```bash
curl -s 127.0.0.1:8000/admin/keys -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{
  "user_id": 1, "label": "ci", "budget_usd": 2.0, "daily_budget_usd": 0.5, "monthly_budget_usd": 1.5, "expires_in_days": 30, "allowed_models": ["claude/haiku", "codex/*"]
}'
curl -s -X PATCH 127.0.0.1:8000/admin/keys/3 -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d '{"budget_usd": null}'      # null clears a limit; omitted fields are left alone
```

Over budget → `429 key_budget_exhausted`; disallowed model → `403 model_not_allowed`; expired → `401`.

The gateway reserves available credits and key budget when a request starts, and settles the actual charge on completion. A reservation prevents concurrent requests from using the same funds. These are **admission limits, not guaranteed hard spending caps**: only the Claude CLI receives a per-run dollar limit, and any backend can report a final cost above its reservation. Direct APIs and the other CLIs do not enforce the dollar limit. Use provider-side spending controls where a hard limit is required.

The **Request usage** page shows outstanding reservations and provides a guarded release action. Its usage explorer filters by user, key, provider, model and UTC date, supports paging, and exports the loaded rows to CSV. Cost totals in the explorer apply only to loaded billed rows; test runs are shown but not billed. The Overview warns when available credits are below $1 or a key has used at least 80% of a budget. Browser alerts can be enabled on the Overview page; they require browser permission and the page to be open. The overview refreshes these checks every minute.

Reservations remain in the database after an unclean shutdown to avoid silently permitting overspend. An administrator can inspect `GET /admin/reservations`. After verifying the associated request has stopped on every instance and reconciling any upstream charges, release an orphan with `DELETE /admin/reservations/{request_id}`; releasing an active reservation allows overspending. The available credit balance excludes outstanding reservations.

### Admin API

Bearer admin token. `GET|POST /admin/users`, `POST /admin/users/{id}/topup`, `GET|POST /admin/keys`,
`PATCH|DELETE /admin/keys/{id}`, `GET /admin/ledger`, `GET /admin/usage/daily`, `GET|POST|PUT|DELETE /admin/providers…`.
Interactive reference at `/docs`. New ledger rows include duration, failure code where available, and the resolved model and rates used for estimated charges; historical rows may not contain these details.

### Routing and estimates

A provider can specify `extra.fallback_model` (also editable on the Providers page) as a `provider/model` ID. The fallback is selected only before work starts when the primary provider is disabled, its CLI binary is absent, or its direct API key is missing. Both requested and fallback models must be allowed by the key. There is no retry after a CLI or upstream request starts, since it might already have incurred charges. Responses identify the selected model and include `X-Proxy-Model`; a fallback also includes `X-Proxy-Requested-Model`.

The Playground can estimate cost using approximate text token counts and an output-token assumption. The estimate excludes image tokens and CLI prompt overhead and is not a spending guarantee. `GET /v1/estimate` accepts `model`, `input_tokens`, and `output_tokens` and returns the rates and estimate for a proxy key.

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
  JSON and omit prompts unless `PROXY_DEBUG_LOG_PROMPTS=true`. The dashboard launch command passes the admin token in a URL fragment, which the dashboard removes after loading; the fragment is not sent in HTTP requests. The login WebSocket authenticates in its first message.
- Global and per-user concurrency, queue timeout, per-key rate limit, request-size and image-size limits. Binds to
  localhost by default.
- Billing: Claude Code reports `total_cost_usd` (used as is). The other CLIs report tokens only, so cost is
  *estimated* from `app/pricing.py` and flagged `estimated` in the ledger. Check that table against current prices.
  Direct API estimates use the resolved model ID. For aliases or prices not covered by the table, set provider
  `extra.pricing_rates` to a map such as `{"actual-model-id": [3.0, 15.0]}` (input and output USD per million tokens).
  CLI aliases such as `default` cannot identify the selected model automatically; configure their rates explicitly. The Providers page offers a pricing editor; it saves with the rest of the provider settings.

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
