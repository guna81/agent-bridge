#!/usr/bin/env bash
set -e

# ==============================================================================
# LLM CLI Gateway (ai-credit-proxy) - Multi-OS Service Manager
# Supports:
#   - macOS (launchd LaunchAgent)
#   - Linux (systemd user service with linger, or supervisor fallback)
# ==============================================================================

# Personal installations use the CLI as the single service owner. Keep the
# legacy server manager available explicitly for existing multi-user deployments.
if [ "${AGENTBRIDGE_LEGACY_SERVICE:-0}" != "1" ]; then
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if command -v agentbridge >/dev/null 2>&1; then
        CLI=(agentbridge)
    else
        CLI=("$REPO_DIR/agentbridge")
    fi
    case "${1:-status}" in
        install) "${CLI[@]}" start; exec "${CLI[@]}" autostart enable ;;
        start|stop|status) exec "${CLI[@]}" "${1:-status}" ;;
        restart) "${CLI[@]}" stop; exec "${CLI[@]}" start ;;
        uninstall) "${CLI[@]}" autostart disable; exec "${CLI[@]}" stop ;;
        logs) exec tail -n 50 -f "${AGENTBRIDGE_HOME:-$HOME/.agentbridge}/service.log" ;;
        menubar)
            case "${2:-start}" in
                build) exec bash "$REPO_DIR/menubar/build.sh" ;;
                start) exec "${CLI[@]}" start ;;
                status) exec "${CLI[@]}" status ;;
                *) echo "Use the dashboard to hide the indicator, or agentbridge stop to stop it." >&2; exit 1 ;;
            esac ;;
        *) echo "Usage: $0 {install|start|stop|restart|status|logs|menubar|uninstall}" >&2; exit 1 ;;
    esac
fi

SERVICE_NAME="ai-credit-proxy"
MACOS_LABEL="com.ai-credit-proxy"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_DIR/backend"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
PORT=8765

# Load port from backend/.env if present
if [ -f "$BACKEND_DIR/.env" ]; then
    ENV_PORT=$(grep -E "^PROXY_PORT=" "$BACKEND_DIR/.env" | cut -d'=' -f2 | tr -d ' "\r\n')
    if [ -n "$ENV_PORT" ]; then
        PORT="$ENV_PORT"
    fi
fi

# Detect Operating System
OS_TYPE="$(uname -s)"
case "$OS_TYPE" in
    Darwin)
        PLATFORM="macos"
        ;;
    Linux)
        PLATFORM="linux"
        ;;
    CYGWIN*|MINGW*|MSYS*)
        PLATFORM="windows"
        ;;
    *)
        PLATFORM="unknown"
        ;;
esac

# Paths per platform
if [ "$PLATFORM" = "macos" ]; then
    LOG_DIR="$HOME/Library/Logs/ai-credit-proxy"
    PLIST_FILE="$HOME/Library/LaunchAgents/${MACOS_LABEL}.plist"
elif [ "$PLATFORM" = "linux" ]; then
    if [ -n "$XDG_STATE_HOME" ]; then
        LOG_DIR="$XDG_STATE_HOME/ai-credit-proxy"
    else
        LOG_DIR="$HOME/.local/state/ai-credit-proxy"
    fi
    SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
    SERVICE_FILE="$SYSTEMD_USER_DIR/${SERVICE_NAME}.service"
else
    LOG_DIR="$HOME/.ai-credit-proxy/logs"
fi

LOG_FILE="$LOG_DIR/server.log"
ERR_LOG_FILE="$LOG_DIR/server.err.log"

check_python() {
    if [ ! -f "$PYTHON_BIN" ]; then
        echo "Error: Python venv not found at $PYTHON_BIN"
        echo "Please set up the environment first:"
        echo "  cd backend && uv sync"
        exit 1
    fi
}

setup_log_dirs() {
    mkdir -p "$LOG_DIR"
    touch "$LOG_FILE" "$ERR_LOG_FILE"
    # Symlink logs into backend/ for local convenience
    ln -sf "$LOG_FILE" "$BACKEND_DIR/server.log" 2>/dev/null || true
    ln -sf "$ERR_LOG_FILE" "$BACKEND_DIR/server.err.log" 2>/dev/null || true
}

find_listening_pids() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true
    elif command -v ss >/dev/null 2>&1; then
        ss -tulpn "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d'=' -f2 | sort -u || true
    elif command -v fuser >/dev/null 2>&1; then
        fuser "$PORT/tcp" 2>/dev/null || true
    fi
}

stop_manual_process_on_port() {
    local pids
    pids=$(find_listening_pids)
    if [ -n "$pids" ]; then
        echo "Found existing process listening on port $PORT (PID(s): $pids). Terminating..."
        for pid in $pids; do
            local cmd
            cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
            if echo "$cmd" | grep -qE "python|run.py"; then
                kill -15 "$pid" 2>/dev/null || true
            fi
        done
        sleep 1
        pids=$(find_listening_pids)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                local cmd
                cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
                if echo "$cmd" | grep -qE "python|run.py"; then
                    kill -9 "$pid" 2>/dev/null || true
                fi
            done
        fi
    fi
}

wait_for_health() {
    echo "Waiting for service to respond on http://127.0.0.1:$PORT..."
    local ready=0
    for _ in {1..20}; do
        if curl -s "http://127.0.0.1:$PORT/healthz" 2>/dev/null | grep -q '"ok":true'; then
            ready=1
            break
        fi
        sleep 0.5
    done

    if [ $ready -eq 1 ]; then
        echo "Service is running successfully!"
        echo "URL: http://127.0.0.1:$PORT"
        echo "Logs: $LOG_FILE"
        echo "Daemon will automatically restart on crash and start on boot/login."
    else
        echo "Warning: Service started but health check (/healthz) did not respond in time."
        echo "Check logs: tail -n 30 $ERR_LOG_FILE"
    fi
}

# ==============================================================================
# macOS Implementation (launchd)
# ==============================================================================

macos_generate_plist() {
    mkdir -p "$HOME/Library/LaunchAgents"
    setup_log_dirs

    cat <<EOF > "$PLIST_FILE"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${MACOS_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${BACKEND_DIR}/run.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${BACKEND_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>USER</key>
        <string>${USER}</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>

    <key>StandardErrorPath</key>
    <string>${ERR_LOG_FILE}</string>
</dict>
</plist>
EOF
    echo "Generated LaunchAgent plist: $PLIST_FILE"
}

macos_is_loaded() {
    launchctl list 2>/dev/null | awk '{print $3}' | grep -Fxq "$MACOS_LABEL"
}

macos_install() {
    echo "Installing $MACOS_LABEL as a macOS LaunchAgent (always running)..."
    macos_generate_plist

    if macos_is_loaded; then
        echo "Unloading existing LaunchAgent..."
        launchctl unload -w "$PLIST_FILE" 2>/dev/null || true
    fi

    stop_manual_process_on_port
    echo "Loading and enabling LaunchAgent..."
    launchctl load -w "$PLIST_FILE"
    wait_for_health
}

macos_start() {
    if [ ! -f "$PLIST_FILE" ]; then
        macos_install
        return
    fi
    if ! macos_is_loaded; then
        stop_manual_process_on_port
        launchctl load -w "$PLIST_FILE"
        echo "Service started."
    else
        echo "Service is already loaded in launchd."
        macos_status
    fi
}

macos_stop() {
    if [ -f "$PLIST_FILE" ] && macos_is_loaded; then
        echo "Stopping service $MACOS_LABEL..."
        launchctl unload -w "$PLIST_FILE" 2>/dev/null || true
    fi
    stop_manual_process_on_port
    echo "Service stopped."
}

macos_restart() {
    echo "Restarting $MACOS_LABEL..."
    macos_stop
    sleep 1
    macos_start
}

macos_status() {
    echo "=== Service Status (macOS launchd: $MACOS_LABEL) ==="
    if macos_is_loaded; then
        local pid
        pid=$(launchctl list | awk -v lbl="$MACOS_LABEL" '$3 == lbl {print $1}')
        echo "LaunchAgent: LOADED"
        if [ "$pid" != "-" ] && [ -n "$pid" ]; then
            echo "Launchd PID: $pid"
        else
            echo "Launchd PID: not running (or between restarts)"
        fi
    else
        echo "LaunchAgent: NOT LOADED"
    fi

    local port_pids
    port_pids=$(find_listening_pids)
    if [ -n "$port_pids" ]; then
        echo "Port $PORT: LISTENING (PID: $port_pids)"
    else
        echo "Port $PORT: NOT LISTENING"
    fi

    local health
    health=$(curl -s "http://127.0.0.1:$PORT/healthz" 2>/dev/null || true)
    if echo "$health" | grep -q '"ok":true'; then
        echo "Health Check (/healthz): OK ($health)"
        echo "Application is UP at http://127.0.0.1:$PORT"
    else
        echo "Health Check (/healthz): FAILED / UNRESPONSIVE"
    fi
    echo "Log file: $LOG_FILE"
}

macos_uninstall() {
    echo "Uninstalling $MACOS_LABEL..."
    macos_stop
    if [ -f "$PLIST_FILE" ]; then
        rm -f "$PLIST_FILE"
        echo "Removed LaunchAgent plist: $PLIST_FILE"
    fi
    echo "Uninstallation complete."
}

# ==============================================================================
# Linux Implementation (systemd user unit)
# ==============================================================================

linux_has_systemd() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1
}

linux_generate_service() {
    mkdir -p "$SYSTEMD_USER_DIR"
    setup_log_dirs

    cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=LLM CLI Gateway (ai-credit-proxy)
After=network.target

[Service]
Type=simple
WorkingDirectory=${BACKEND_DIR}
ExecStart=${PYTHON_BIN} ${BACKEND_DIR}/run.py
Restart=always
RestartSec=3
Environment="PATH=${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
Environment="HOME=${HOME}"
Environment="USER=${USER}"
Environment="PYTHONUNBUFFERED=1"
StandardOutput=append:${LOG_FILE}
StandardError=append:${ERR_LOG_FILE}

[Install]
WantedBy=default.target
EOF
    echo "Generated systemd user service: $SERVICE_FILE"
}

linux_install() {
    echo "Installing $SERVICE_NAME as a Linux systemd user service..."
    linux_generate_service

    echo "Reloading systemd user daemon..."
    systemctl --user daemon-reload

    # Enable linger so service runs even when SSH session disconnects
    if command -v loginctl >/dev/null 2>&1; then
        echo "Enabling linger for $USER (keeps service running without active login session)..."
        loginctl enable-linger "$USER" 2>/dev/null || true
    fi

    stop_manual_process_on_port
    echo "Enabling and starting $SERVICE_NAME.service..."
    systemctl --user enable --now "$SERVICE_NAME.service"
    wait_for_health
}

linux_start() {
    if [ ! -f "$SERVICE_FILE" ]; then
        linux_install
        return
    fi
    stop_manual_process_on_port
    systemctl --user start "$SERVICE_NAME.service"
    echo "Service started."
}

linux_stop() {
    if systemctl --user is-active --quiet "$SERVICE_NAME.service" 2>/dev/null; then
        echo "Stopping service $SERVICE_NAME..."
        systemctl --user stop "$SERVICE_NAME.service"
    fi
    stop_manual_process_on_port
    echo "Service stopped."
}

linux_restart() {
    echo "Restarting $SERVICE_NAME..."
    systemctl --user restart "$SERVICE_NAME.service"
    wait_for_health
}

linux_status() {
    echo "=== Service Status (Linux systemd: $SERVICE_NAME) ==="
    if systemctl --user is-active --quiet "$SERVICE_NAME.service" 2>/dev/null; then
        echo "systemd Unit: ACTIVE (Running)"
    else
        echo "systemd Unit: INACTIVE"
    fi

    local port_pids
    port_pids=$(find_listening_pids)
    if [ -n "$port_pids" ]; then
        echo "Port $PORT: LISTENING (PID: $port_pids)"
    else
        echo "Port $PORT: NOT LISTENING"
    fi

    local health
    health=$(curl -s "http://127.0.0.1:$PORT/healthz" 2>/dev/null || true)
    if echo "$health" | grep -q '"ok":true'; then
        echo "Health Check (/healthz): OK ($health)"
        echo "Application is UP at http://127.0.0.1:$PORT"
    else
        echo "Health Check (/healthz): FAILED / UNRESPONSIVE"
    fi
    echo "Log file: $LOG_FILE"
}

linux_uninstall() {
    echo "Uninstalling $SERVICE_NAME..."
    systemctl --user disable --now "$SERVICE_NAME.service" 2>/dev/null || true
    if [ -f "$SERVICE_FILE" ]; then
        rm -f "$SERVICE_FILE"
        systemctl --user daemon-reload
        echo "Removed systemd service: $SERVICE_FILE"
    fi
    echo "Uninstallation complete."
}

show_logs() {
    setup_log_dirs
    echo "Streaming logs (Press Ctrl+C to exit)..."
    tail -n 50 -f "$LOG_FILE" "$ERR_LOG_FILE"
}

manage_menubar() {
    local action="${2:-start}"
    local MENUBAR_BIN="$REPO_DIR/menubar/LLMGatewayBar"
    local APP_PATH="$REPO_DIR/menubar/LLMGatewayBar.app"

    case "$action" in
        build)
            bash "$REPO_DIR/menubar/build.sh"
            ;;
        start)
            if [ ! -f "$MENUBAR_BIN" ]; then
                echo "Building menu bar app first..."
                bash "$REPO_DIR/menubar/build.sh"
            fi
            if pgrep -x "LLMGatewayBar" >/dev/null 2>&1; then
                echo "Menu Bar app is already running."
            else
                echo "Starting LLM Gateway Menu Bar app..."
                open -a "$APP_PATH" 2>/dev/null || ("$MENUBAR_BIN" >/dev/null 2>&1 &)
                sleep 0.5
                if pgrep -x "LLMGatewayBar" >/dev/null 2>&1; then
                    echo "✓ LLM Gateway Menu Bar app is now active in your macOS status bar."
                else
                    echo "Could not start menu bar app."
                fi
            fi
            ;;
        stop)
            echo "Stopping LLM Gateway Menu Bar app..."
            pkill -x "LLMGatewayBar" 2>/dev/null || true
            echo "Stopped."
            ;;
        restart)
            manage_menubar menubar stop
            sleep 0.5
            manage_menubar menubar start
            ;;
        status)
            if pgrep -x "LLMGatewayBar" >/dev/null 2>&1; then
                local pid=$(pgrep -x "LLMGatewayBar" | head -n1)
                echo "Menu Bar App: RUNNING (PID: $pid)"
            else
                echo "Menu Bar App: NOT RUNNING"
            fi
            ;;
        *)
            echo "Usage: $0 menubar {start|stop|restart|status|build}"
            ;;
    esac
}

# ==============================================================================
# Dispatcher
# ==============================================================================

if [ "$PLATFORM" = "windows" ]; then
    echo "Detected Windows environment."
    echo "For native Windows, run the PowerShell manager:"
    echo "  powershell -ExecutionPolicy Bypass -File .\\manage-service.ps1 $1"
    echo "Or run within WSL2 (Ubuntu), PM2, or Docker Compose."
    exit 1
fi

check_python

case "$1" in
    install)
        if [ "$PLATFORM" = "macos" ]; then
            macos_install
        else
            linux_install
        fi
        ;;
    start)
        if [ "$PLATFORM" = "macos" ]; then
            macos_start
        else
            linux_start
        fi
        ;;
    stop)
        if [ "$PLATFORM" = "macos" ]; then
            macos_stop
        else
            linux_stop
        fi
        ;;
    restart)
        if [ "$PLATFORM" = "macos" ]; then
            macos_restart
        else
            linux_restart
        fi
        ;;
    status)
        if [ "$PLATFORM" = "macos" ]; then
            macos_status
        else
            linux_status
        fi
        ;;
    logs)
        show_logs
        ;;
    menubar)
        if [ "$PLATFORM" != "macos" ]; then
            echo "Error: Native menu bar app is currently supported on macOS."
            exit 1
        fi
        manage_menubar "$@"
        ;;
    uninstall)
        if [ "$PLATFORM" = "macos" ]; then
            macos_uninstall
        else
            linux_uninstall
        fi
        ;;
    *)
        echo "LLM CLI Gateway (ai-credit-proxy) - Service Manager"
        echo "Detected Platform: $PLATFORM"
        echo ""
        echo "Usage: $0 {install|start|stop|restart|status|logs|menubar|uninstall}"
        echo ""
        echo "Commands:"
        echo "  install    Install as a background daemon (LaunchAgent on macOS, systemd on Linux) and start"
        echo "  start      Start the background service"
        echo "  stop       Stop the background service"
        echo "  restart    Restart the service"
        echo "  status     Check if service and port $PORT are active and healthy"
        echo "  logs       Stream live server logs"
        echo "  menubar    Manage macOS Status Bar / Menu Bar app (start|stop|restart|status|build)"
        echo "  uninstall  Stop service and remove service definition"
        exit 1
        ;;
esac
