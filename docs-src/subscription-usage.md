# Subscription usage

AgentBridge reads the usage limits of your agent subscriptions and shows them in the dashboard (**Subscription usage**) and in the [status indicator](status-indicator.md).

## What you see

- The **5-hour** window and the **weekly** window for each supported provider.
- When each window **resets**.
- When the data was last updated.

## How it is collected

| Provider | Source |
|---|---|
| Claude | Refreshed in the background **every 2 minutes** using your existing Claude Code login |
| Codex | Rate-limit data read from Codex |
| Antigravity | Quota data, cached |

Availability varies by provider and platform. Install and sign in to each CLI separately.

## Reading the numbers

- A **missing** value is shown as *unavailable*. It does **not** mean the limit is zero.
- Bars and the indicator show **remaining** capacity, so they shrink as you use more.
- If a refresh fails, AgentBridge keeps the **last values** and shows an error. After rate limiting it waits longer before retrying.
- If Claude's login expires, sign in through Claude Code again.
- The indicator's refresh interval controls how often it reads from the gateway, not how often the gateway contacts Claude.
- A custom Claude JSON path is read as a local snapshot and doesn't use the default account's live login.
