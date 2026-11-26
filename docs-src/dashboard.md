# Dashboard

Open it with `agentbridge dashboard`. The command signs you in automatically: the token travels in a URL fragment, which the browser never sends to the server and the dashboard removes after loading.

![AgentBridge Dashboard Overview](../assets/ui-dashboard.png)

## Pages

| Page | Use it to |
|---|---|
| **Overview** | See credits and budget warnings. Warns when available credits drop below $1 or a key has used 80% of a budget. Optional browser alerts need browser permission and the page to be open; checks refresh every minute. |
| **Subscription usage** | View 5-hour and weekly limits and reset times. See [Subscription usage](subscription-usage.md). |
| **Status indicator** | Configure the menu bar or tray display. See [Status indicator](status-indicator.md). |
| **Instructions** | Edit global and per-agent instructions and link them into Claude Code, Codex and Antigravity. See [Skills and instructions](skills-and-instructions.md). |
| **Skills** | Create, validate, edit and symlink shared skills and Claude Code wrappers. See [Skills and instructions](skills-and-instructions.md). |
| **Providers** | Enable providers, choose sign-in, models, default mode and advanced settings. See [Providers](providers.md). |
| **Keys & users** | Add users, add credits, create and limit keys. See [Keys, users and budgets](keys-and-users.md). |
| **Request usage** | Inspect request history, outstanding reservations and export CSV. |
| **Playground** | Chat with any enabled model and estimate cost. |
| **Quick start** | Copy-paste client code. |

### Subscription usage

Inspect live remaining usage windows and reset times across your configured agents:

![Subscription usage view in dashboard](../assets/ui-subscription-usage.png)

### Status indicator settings

Customize which agent quotas appear in the menu bar and choose between usage bars or a compact mark:

![Status indicator settings in dashboard](../assets/ui-status-indicator.png)

### Providers

Configure personal CLI logins or direct API keys, select default models, and run test completions:

![Providers configuration in dashboard](../assets/ui-providers.png)

## Request usage

The usage explorer filters by user, key, provider, model and UTC date, pages through results, and exports the loaded rows to CSV. Cost totals count only loaded billed rows; test runs are shown but not billed.

It also lists **outstanding reservations** with a guarded release action. See [reservations](keys-and-users.md#reservations).

## Cost estimates in the Playground

The estimate uses approximate text token counts and an output-token assumption. It excludes image tokens and CLI prompt overhead and is not a spending guarantee. The same estimate is available from `GET /v1/estimate`.
