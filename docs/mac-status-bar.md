# macOS Menu Bar / Status Bar App

The **LLM Gateway Status Bar Companion** (`LLMGatewayBar`) is a lightweight, native macOS Swift application that lives directly in your macOS top menu bar / status bar.

It provides real-time visibility into the exact subscription rate limits and usage for **Google Antigravity**, **Claude Code**, and **OpenAI Codex**, matching their native terminal `/usage` output.

---

## Live Monitored Metrics

### 1. Google Antigravity (via embedded Language Server ConnectRPC)
- **Subscription Tier**: e.g. `Google AI Pro (g1-pro-tier)`
- **Gemini 5h limit**: `99% left (Resets 12:23 AM)`
- **Gemini Weekly limit**: `52% left (Resets Nov 14 at 12:01 PM)`
- **Claude / GPT 5h limit (3p)**: `100% left (Resets 12:30 AM)`
- **Claude / GPT Weekly limit (3p)**: `100% left (Resets Nov 19 at 7:30 PM)`

### 2. Claude Code (from `~/.claude.json`)
- **Current session**: `7% used (Resets 9:09pm)`
- **Current week (all models)**: `93% used (Resets Nov 15 at 9:29am)`
- **Current week (Fable / Scoped)**: `61% used (Resets Nov 15 at 9:29am)`

### 3. OpenAI Codex (from `~/.codex/logs_2.sqlite`)
- **5h limit**: `0% left (Resets 9:31 PM)`
- **Weekly limit**: `48% left (Resets 1:50 PM on 18 Nov)`

---

## Status Bar Display Features

- **Progress Bar Indicator**:
  - For Antigravity & Codex: Displays filled progress bar of **% left** (Red outline when exhausted).
  - For Claude Code: Displays filled progress bar of **% used** (Green `< 70%`, Amber `70%-90%`, Red `≥ 90%`).
  - Blue pulsing indicator (`⚡`) when requests are actively running through the proxy.
- **One-Click Switcher**:
  Click any limit in the menu dropdown to instantly pin it to your macOS top status bar:
  - Antigravity: Gemini 5h
  - Antigravity: Gemini Weekly
  - Antigravity: Claude/GPT 5h
  - Antigravity: Claude/GPT Weekly
  - Claude: Current session
  - Claude: Current week (all models)
  - Claude: Current week (Fable)
  - Codex: 5h limit
  - Codex: Weekly limit
- **Status Bar Formats**:
  - `Standard` (e.g. `agy 5h: 99% left` / `claude: 7% used` / `codex 5h: 0% left`)
  - `Full Details` (e.g. `agy 5h: 99% left (12:23 AM)`)
  - `Progress Bar Only`
- **Bi-directional Configuration Sync**:
  Preferences (active providers, pinned metric) set in the Web Dashboard or Status Bar dropdown stay automatically synchronized in real-time.

---

## Quick Controls

```bash
# Check status
./manage-service.sh menubar status

# Restart / reload changes
./manage-service.sh menubar restart

# Stop app
./manage-service.sh menubar stop

# Rebuild from source
./manage-service.sh menubar build
```
