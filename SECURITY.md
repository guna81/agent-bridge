# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use the repository's private vulnerability reporting
("Security" tab → "Report a vulnerability") and include steps to reproduce. You should get a reply within a week.

## What this server does, and what to expect of it

The proxy runs third-party command-line agents as subprocesses on behalf of API callers. Treat it accordingly:

- Keep it bound to localhost, or put a TLS reverse proxy in front (`docs/reverse-proxy.md`).
- **Agent mode lets callers make the CLI run commands and edit files as the server's user.** Only enable it for
  callers you trust, ideally inside a container. Never combine "skip all permission prompts" with untrusted callers.
- Raw mode reduces what a CLI can do but is best-effort for CLIs whose built-in tools cannot be removed
  (`docs/raw-mode.md`). The provided Docker setup (read-only root, no capabilities) is the recommended isolation.
- The admin token grants full control, including provider API keys' use. Rotate it if it may have leaked: change
  `PROXY_ADMIN_TOKEN` (or delete `data/admin_token`) and restart.
- Changing `PROXY_KEY_PEPPER` invalidates every issued key. Losing `PROXY_SECRET_KEY` makes stored provider API
  keys unreadable.
