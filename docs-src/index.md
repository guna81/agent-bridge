# AgentBridge

AgentBridge brings two workflows together:

- **Track subscription usage** for supported coding agents (Claude Code, Codex, Antigravity and others): 5-hour and weekly limits and their reset times.
- **Expose agent CLIs as an API.** A local gateway offers OpenAI-compatible (`/v1/chat/completions`) and Anthropic-compatible (`/v1/messages`) endpoints on top of the CLIs you have configured.

Everything runs on your machine. The `agentbridge` command starts the gateway, opens a web dashboard and shows usage in the macOS menu bar or the Windows/Linux system tray.

![AgentBridge Dashboard Overview](../assets/ui-dashboard.png)

![AgentBridge Status Bar in macOS Menu Bar](../assets/status-bar-bars.png)

## Where to start

| I want to... | Go to |
|---|---|
| Install AgentBridge | [Install](install.md) |
| Get a first request working in a few minutes | [Quick start](quickstart.md) |
| See my Claude or Codex limits in the menu bar | [Status indicator](status-indicator.md) |
| Point my own code or tools at the gateway | [API reference](api.md) |
| Set spending limits for a key | [Keys, users and budgets](keys-and-users.md) |
| Keep the gateway running all the time | [Deployment](deployment.md) |
| Fix something that isn't working | [Troubleshooting](troubleshooting.md) |

## How it works

```text
 your app / SDK ──HTTP──▶  AgentBridge gateway  ──subprocess──▶  claude / codex / agy / gemini
 (OpenAI or Anthropic        127.0.0.1:43187                       (your existing CLI logins)
  client library)                 │
                                  ├── web dashboard (providers, keys, usage, playground)
                                  └── menu bar / tray indicator (subscription usage)
```

Each request runs the provider's CLI as a subprocess in a fresh temporary directory with a minimal environment. The gateway keeps a ledger of usage and charges it to the caller's credits.

## Platforms

| Platform | Package | Indicator |
|---|---|---|
| macOS (Apple Silicon) | Prebuilt | Native menu bar item |
| Linux (x86-64, glibc, Ubuntu 22.04 or newer) | Prebuilt | System tray (X11 desktop) |
| Windows (x86-64) | Prebuilt | System tray |

!!! note
    Release binaries are unsigned. Windows and Linux packages are built and smoke-tested in CI, but interactive tray and provider-login behaviour still needs more desktop testing.

!!! warning "Subscription logins are for personal use"
    Anthropic's terms restrict consumer-subscription OAuth tokens to Claude Code and Claude.ai. Check the terms of any other provider before using its subscription credentials through a gateway.

## Roadmap

These are plans, not available features: **multi-agent orchestration** (a master agent that delegates to others) and an **LLM router** (choosing a model by task complexity).

## License

AgentBridge is open source under the [MIT license](https://github.com/guna81/agent-bridge/blob/main/LICENSE).
