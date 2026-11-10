# Always-Running Service Guide

This guide explains how to run **LLM CLI Gateway (ai-credit-proxy)** as a persistent, high-availability background service across **macOS**, **Linux**, **Windows**, and **Docker**.

---

## What "Always-Running" Means

When configured as a daemon/service, the gateway provides:
1. **Auto-Restart on Crash (`KeepAlive`)**: If an unhandled exception or process termination occurs, the supervisor immediately relaunches the app.
2. **Boot / Login Persistence**: Automatically starts whenever the system boots or the user logs in—no terminal session required.
3. **Credential & Environment Preservation**: Runs in the user context with access to `$HOME`, preserving CLI logins and credentials (`~/.claude`, `~/.codex`, `~/.gemini`, etc.).
4. **Log Rotation & Monitoring**: Outputs stdout/stderr to dedicated log files and exposes `/healthz` for health checks.

---

## Operating System Matrix

| OS / Runtime | Technology | Manager Script | Auto-Restart | Boot Persistence | No Sudo/Root Needed |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **macOS** | `launchd` LaunchAgent | `./manage-service.sh` |  |  |  |
| **Linux (Ubuntu, Debian, Fedora, Arch, RHEL)** | `systemd` user service | `./manage-service.sh` |  |  |  |
| **Windows** | Windows Task Scheduler / VBS | `.\manage-service.ps1` |  |  |  |
| **Windows (WSL2)** | `systemd` in WSL2 | `./manage-service.sh` |  |  |  |
| **Any OS (Docker)** | Docker Engine (`restart: unless-stopped`) | `docker compose up -d` |  |  |  |
| **Any OS (Node.js)** | PM2 Process Manager | `pm2 start ecosystem.config.cjs`|  |  |  |

---

## 1. macOS (Native launchd)

macOS uses `launchd` to manage background daemons. The gateway installs a user LaunchAgent into `~/Library/LaunchAgents/com.ai-credit-proxy.plist`.

### Quick Commands

```bash
# 1. Install and start the LaunchAgent daemon
./manage-service.sh install

# 2. Check service status, PID, and health
./manage-service.sh status

# 3. Stream live logs in real time
./manage-service.sh logs

# 4. Restart the service
./manage-service.sh restart

# 5. Stop the service
./manage-service.sh stop

# 6. Uninstall and remove from LaunchAgents
./manage-service.sh uninstall
```

### Technical Details
- **Plist Location**: `~/Library/LaunchAgents/com.ai-credit-proxy.plist`
- **Log Files**: `~/Library/Logs/ai-credit-proxy/server.log` and `server.err.log` (symlinked in `backend/server.log`)
- **Key Flags**:
  - `<key>KeepAlive</key><true/>`: Guarantees automatic relaunch if killed or crashed.
  - `<key>RunAtLoad</key><true/>`: Boots the service when your user session starts.

---

## 2. Linux (systemd User Service)

On Linux distributions with `systemd` (Ubuntu, Debian, Fedora, Arch, Rocky, CentOS, openSUSE), the gateway runs as a **systemd user service**. This requires **no root/sudo privileges** and preserves your user home directory and CLI credentials.

### Quick Commands

```bash
# 1. Install, enable linger, and start the systemd user service
./manage-service.sh install

# 2. Check status and health
./manage-service.sh status

# 3. View live logs
./manage-service.sh logs

# 4. Restart the service
./manage-service.sh restart

# 5. Stop the service
./manage-service.sh stop

# 6. Uninstall the systemd unit
./manage-service.sh uninstall
```

### Native systemctl Commands

You can also inspect and manage the service directly via `systemctl`:

```bash
systemctl --user status ai-credit-proxy.service
journalctl --user -u ai-credit-proxy.service -f
systemctl --user restart ai-credit-proxy.service
```

### Keeping the Service Running Without Active SSH Sessions (Linger)

By default, Linux systemd terminates user services when all SSH/desktop sessions log out. `./manage-service.sh install` automatically executes:

```bash
loginctl enable-linger "$USER"
```

This instructs systemd to keep your user service running 24/7 across logouts and server reboots.

- **Unit File**: `~/.config/systemd/user/ai-credit-proxy.service`
- **Log Files**: `~/.local/state/ai-credit-proxy/server.log` (or `~/.ai-credit-proxy/logs/server.log`)

---

## 3. Windows

### Option A: PowerShell Task Scheduler (Native Windows)

On Windows, `manage-service.ps1` registers a persistent Windows Scheduled Task that launches at user login, runs silently in the background (no console pop-up), and restarts automatically on failure.

Open PowerShell in the project directory:

```powershell
# 1. Install and start background task
powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 install

# 2. Check status
powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 status

# 3. Stream live logs
powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 logs

# 4. Restart service
powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 restart

# 5. Stop service
powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 stop

# 6. Uninstall
powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 uninstall
```

- **Logs Location**: `%USERPROFILE%\.ai-credit-proxy\logs\server.log`

### Option B: Windows Subsystem for Linux (WSL2 - Recommended for AI CLIs)

Most AI coding CLIs (such as Claude Code or Codex) perform best in a Linux environment. If you run WSL2:
1. Open your WSL2 terminal (Ubuntu).
2. Clone/navigate to the project repository.
3. Run the standard Linux command:
   ```bash
   ./manage-service.sh install
   ```

### Option C: NSSM (Non-Sucking Service Manager)

If you need a true Windows system service (runs before user logon):
```powershell
nssm install AICreditProxy "C:\path\to\ai-credit-proxy\backend\.venv\Scripts\python.exe" "run.py"
nssm set AICreditProxy AppDirectory "C:\path\to\ai-credit-proxy\backend"
nssm set AICreditProxy AppStdout "C:\path\to\ai-credit-proxy\backend\server.log"
nssm set AICreditProxy AppStderr "C:\path\to\ai-credit-proxy\backend\server.err.log"
nssm start AICreditProxy
```

---

## 4. Universal Option: Docker Compose

Docker works identically across **macOS**, **Linux**, and **Windows**.

The included `docker-compose.yml` is configured with `restart: unless-stopped`:

```bash
# 1. Prepare environment
cp .env.example .env
# Edit .env and set PROXY_SECRET_KEY, PROXY_ADMIN_TOKEN

# 2. Build and launch in detached mode
docker compose up -d --build

# 3. Check status
docker compose ps

# 4. Follow logs
docker compose logs -f

# 5. Stop
docker compose down
```

> **Note on CLI Logins with Docker**:
> Docker runs in container isolation. To reuse CLI accounts (Claude, Codex, AGY) without passing API keys, mount the user's CLI credential folders into the container or deploy natively using `./manage-service.sh`.

---

## 5. Universal Option: PM2 (Node.js)

If you have Node.js and PM2 installed, you can use the included `ecosystem.config.cjs`:

```bash
npm install -g pm2

# Start daemon
pm2 start ecosystem.config.cjs

# Make it persist across system reboots
pm2 save
pm2 startup

# Monitor and logs
pm2 status
pm2 logs ai-credit-proxy
```

---

## Health Check & Monitoring

Every service installation can be monitored using:

```bash
# Basic liveness check (returns {"ok":true})
curl -s http://127.0.0.1:8765/healthz

# Prometheus metrics (if PROXY_METRICS_PUBLIC=true or with admin Bearer token)
curl -s http://127.0.0.1:8765/metrics
```

---

## Troubleshooting

### Port Already in Use (`[Errno 48]` or `[Errno 98]`)
If another process is using port `8765` (or the port defined in `backend/.env`):
- Run `./manage-service.sh status` to see the listening PID.
- Run `./manage-service.sh stop` or `./manage-service.sh restart` to cleanly terminate and relaunch.

### CLI Credentials Not Found
If the service starts but cannot find your provider CLIs (`claude`, `codex`, `agy`):
- Verify the CLI is in your user `PATH` (e.g. `~/.local/bin` or `/opt/homebrew/bin`).
- The service definitions in `manage-service.sh` automatically include standard user binary directories (`~/.local/bin`, `/usr/local/bin`, `/opt/homebrew/bin`, `/usr/bin`, `/bin`).
