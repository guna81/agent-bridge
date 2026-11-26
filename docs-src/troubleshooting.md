# Troubleshooting

## First checks

```sh
agentbridge status          # gateway health and address
curl http://127.0.0.1:43187/healthz     # should return 200
```

## Logs

| Log | Location |
|---|---|
| Tray (Windows, Linux) | `~/.agentbridge/tray.log` |
| Menu bar (macOS) | `~/.agentbridge/status-bar.log` |
| Login startup | `~/.agentbridge/autostart.log` |

`~/.agentbridge` moves if you set `AGENTBRIDGE_HOME`.

## Common problems

??? question "`agentbridge: command not found`"
    On macOS and Linux, add `~/.local/bin` to your `PATH`. On Windows, open a new terminal after installing.

??? question "A provider card says *not installed*"
    The CLI binary isn't on the gateway user's `PATH`. Install it and restart the gateway.

??? question "A provider card says *not signed in*"
    That CLI has no login or API key for the gateway user. Sign in to the CLI, or add an API key / use **Connect account** on the provider card. Reusing CLI logins on a separately configured server needs `PROXY_SINGLE_USER_PERSONAL_USE=true`.

??? question "Usage shows *unavailable*, or looks stale"
    *Unavailable* means the value couldn't be read; it doesn't mean zero. After a failed refresh the last values are kept and an error is shown, and retries slow down after rate limiting. For Claude, sign in through Claude Code again if the login expired. See [Subscription usage](subscription-usage.md).

??? question "No menu bar or tray indicator"
    - Check it isn't turned off on the **Status indicator** page.
    - Did you start with `--no-tray`? Restart without it.
    - Linux needs an X11 desktop with a system tray.
    - Read `status-bar.log` or `tray.log`. The gateway keeps running if the helper fails; `agentbridge start` restarts a missing helper.

??? question "Port already in use"
    Start on another port: `agentbridge start --port 43188`. For source services, run `./manage-service.sh status` to see the process listening, then `stop` or `restart`. Don't run the packaged CLI and a source service on the same port.

??? question "Doesn't start at login"
    Check `agentbridge autostart status` and `~/.agentbridge/autostart.log`. On macOS, login jobs may be blocked from reading a source checkout under Desktop, Documents or Downloads; use a packaged install. Linux needs a desktop that supports XDG autostart.

??? question "macOS or Windows warns about an unidentified developer"
    Release binaries are unsigned. Verify the download came from the project's releases page before allowing it.

??? question "`429 key_budget_exhausted` / `403 model_not_allowed` / `401`"
    The key is over budget, not allowed for that model, or expired or invalid. Adjust it under **Keys & users**. See [Keys, users and budgets](keys-and-users.md).

??? question "Images are rejected with 400"
    Images must be inline base64, and only `claude`, `codex` and the direct-API backend accept them. CLI providers accept images only in the last user message.

??? question "Tool calls come back as plain text or not at all"
    Function calling is emulated through the prompt, so a model can occasionally ignore the format. See [API reference](api.md#behaviour-to-know).

??? question "`temperature` or `max_tokens` has no effect"
    CLIs don't accept them. Check the `X-Proxy-Ignored-Params` response header. The Direct API backend honours them.

??? question "Codex models are missing"
    Discovery only works with the shared host CLI login. Press **Refresh discovered models**, or add models manually for API-key or per-user logins. See [Models](models.md#codex-model-discovery).

## FAQ

**Does it work offline?** The gateway is local, but the agent CLIs call their providers over the internet.

**Are my prompts stored?** Prompts aren't logged unless `PROXY_DEBUG_LOG_PROMPTS=true`. Usage and cost records are kept in the local database.

**Where is my data?** In `~/.agentbridge`. `agentbridge uninstall` keeps it; add `--purge` to delete it.

**Can I expose it to my team?** Only behind a TLS reverse proxy, with `PROXY_SINGLE_USER_PERSONAL_USE=false`. See [Deployment](deployment.md#exposing-beyond-localhost).

Still stuck? [Open an issue](https://github.com/guna81/agent-bridge/issues) with your OS, `agentbridge --version`, and the relevant log lines (remove any secrets).
