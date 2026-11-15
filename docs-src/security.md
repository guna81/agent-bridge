# Security

Report vulnerabilities as described in [SECURITY.md](https://github.com/guna81/agent-bridge/blob/main/SECURITY.md).

## Model

- **Per-request isolation.** Each request gets a fresh temporary working directory (deleted afterwards), a minimal environment (PATH, HOME, locale and proxy/CA variables only), no server secrets, and its own process group, killed on timeout or client disconnect.
- **Key storage.** Proxy keys are hashed (HMAC-SHA256 with a pepper). Provider API keys are Fernet-encrypted at rest.
- **Logging.** Logs are structured JSON and omit prompts unless `PROXY_DEBUG_LOG_PROMPTS=true`.
- **Dashboard sign-in.** `agentbridge dashboard` passes the admin token in a URL fragment, which the browser doesn't send and the dashboard removes after loading. The login WebSocket authenticates in its first message.
- **Limits.** Global and per-user concurrency, queue timeout, per-key rate limit, request-size and image-size limits.
- **Network.** Binds to loopback by default.

## Things to be careful with

!!! danger "Agent mode"
    Agent mode can run commands and edit files as the server user. Enable it only for trusted callers.

!!! warning "Subscription logins"
    Reusing a consumer-subscription login is for personal use. Keep `PROXY_SINGLE_USER_PERSONAL_USE=false` on any server other people use.

- **Spending limits are admission limits**, not hard caps. See [Keys, users and budgets](keys-and-users.md#limits-are-admission-limits-not-hard-caps).
- **Don't expose the gateway without TLS.** See [Deployment](deployment.md#exposing-beyond-localhost).
- **Binaries are unsigned.** The one-line installers download and run scripts; you can read and run them locally instead. Checksums detect corrupt downloads but don't authenticate the publisher.
- **Back up** `PROXY_SECRET_KEY` and `PROXY_KEY_PEPPER`.

## Billing data

Claude Code reports `total_cost_usd`, used as is. Other CLIs report tokens only, so cost is estimated from the price table and flagged `estimated` in the ledger. Check it against current prices; see [Providers](providers.md#pricing).
