# Configuration

## Where things live

| What | Location |
|---|---|
| Data, database, secrets, logs | `~/.agentbridge` (override with `AGENTBRIDGE_HOME`) |
| Status indicator settings | `status_bar_config.json` in the data directory |
| Logs | `tray.log` (Windows/Linux), `status-bar.log` (macOS), `autostart.log` |
| Source server settings | `backend/.env` (copy from `.env.example`) |

The packaged CLI binds to `127.0.0.1:43187` by default. The standalone source server (`backend/run.py`) uses port `8000`.

## Server settings (`PROXY_*`)

Set these in `backend/.env` for the source server.

### Core

| Variable | Default | Purpose |
|---|---|---|
| `PROXY_SECRET_KEY` | none (required) | Fernet key that encrypts provider API keys at rest. Generate with `uv run python -m app.security` from `backend/`. Back it up: losing it loses stored API keys. |
| `PROXY_ADMIN_TOKEN` | auto-generated | Token for the UI and `/admin/*`. If blank, one is written to `<data_dir>/admin_token`. |
| `PROXY_KEY_PEPPER` | `change-me` | Pepper for hashing proxy keys. Changing it invalidates every key. |
| `PROXY_HOST` | `127.0.0.1` | Bind address. Keep it unless a TLS reverse proxy is in front. |
| `PROXY_PORT` | `8000` | Port for the source server |
| `PROXY_DATA_DIR` | `./data` | Data directory |
| `PROXY_SINGLE_USER_PERSONAL_USE` | `false` | Allows `oauth_cli` and reuse of the server user's CLI login. Leave `false` for anything other people use. |

### Limits

| Variable | Default | Purpose |
|---|---|---|
| `PROXY_MAX_CONCURRENCY` | `4` | Global concurrent requests |
| `PROXY_PER_USER_CONCURRENCY` | `2` | Concurrent requests per user |
| `PROXY_QUEUE_TIMEOUT_S` | `30` | Wait in the queue before failing |
| `PROXY_REQUEST_TIMEOUT_S` | `300` | Per-request timeout |
| `PROXY_MAX_BODY_BYTES` | `10485760` | Max request body (leaves room for base64 images) |
| `PROXY_MAX_IMAGE_BYTES` | `5242880` | Max size per image |
| `PROXY_MAX_IMAGES` | `8` | Max images per request |
| `PROXY_RATE_LIMIT_PER_MINUTE` | `60` | Per-key rate limit |
| `PROXY_DEFAULT_MAX_BUDGET_USD` | `0.50` | Default per-request spend limit |

### Logging, storage and metrics

| Variable | Default | Purpose |
|---|---|---|
| `PROXY_DEBUG_LOG_PROMPTS` | `false` | Prompts are never logged unless `true` |
| `PROXY_DATABASE_URL` | blank (SQLite) | e.g. `postgresql+psycopg://user:pass@host:5432/proxy` |
| `PROXY_QUEUE_BACKEND` | `local` | `local` or `redis` |
| `PROXY_REDIS_URL` | blank | e.g. `redis://host:6379/0` |
| `PROXY_METRICS_PUBLIC` | `false` | Let `/metrics` be read without the admin token |

## Scaling out

- **Postgres:** `uv sync --extra postgres`, then set `PROXY_DATABASE_URL`. Tables are created and upgraded on start.
- **Several instances:** `uv sync --extra redis`, `PROXY_QUEUE_BACKEND=redis`, `PROXY_REDIS_URL=...`. Concurrency limits and the per-key rate limit are then shared. Per-user CLI logins live on disk (`data/homes`), so use API-key auth or a shared volume with more than one instance.
- **Metrics:** `GET /metrics` in Prometheus text format (requests, tokens, cost, duration, queue).

## Installer and CLI variables

See [Install](install.md#installer-options) and [Command line](cli.md#environment-variables).
