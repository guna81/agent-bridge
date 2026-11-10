#!/usr/bin/env bash
set -e

# Configuration
SERVICE_LABEL="com.ai-credit-proxy"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_DIR/backend"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
LOG_DIR="$HOME/Library/Logs/ai-credit-proxy"
LOG_FILE="$LOG_DIR/server.log"
ERR_LOG_FILE="$LOG_DIR/server.err.log"
PLIST_FILE="$HOME/Library/LaunchAgents/${SERVICE_LABEL}.plist"
PORT=8765

# Load port from backend/.env if present
if [ -f "$BACKEND_DIR/.env" ]; then
    ENV_PORT=$(grep -E "^PROXY_PORT=" "$BACKEND_DIR/.env" | cut -d'=' -f2 | tr -d ' "\r\n')
    if [ -n "$ENV_PORT" ]; then
        PORT="$ENV_PORT"
    fi
fi

# Ensure Python binary exists
check_python() {
    if [ ! -f "$PYTHON_BIN" ]; then
        echo "Error: Python venv not found at $PYTHON_BIN"
        echo "Please run: cd backend && uv sync"
        exit 1
    fi
}

generate_plist() {
    mkdir -p "$HOME/Library/LaunchAgents"
    mkdir -p "$LOG_DIR"
    touch "$LOG_FILE" "$ERR_LOG_FILE"

    # Create convenient symlinks in backend/
    ln -sf "$LOG_FILE" "$BACKEND_DIR/server.log" 2>/dev/null || true
    ln -sf "$ERR_LOG_FILE" "$BACKEND_DIR/server.err.log" 2>/dev/null || true

    cat <<EOF > "$PLIST_FILE"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${SERVICE_LABEL}</string>

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

stop_manual_process_on_port() {
    local pids
    pids=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Found existing process listening on port $PORT (PID(s): $pids). Terminating..."
        for pid in $pids; do
            # Only kill if it's actually running python or run.py
            local cmd
            cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
            if echo "$cmd" | grep -qE "python|run.py"; then
                kill -15 "$pid" 2>/dev/null || true
            fi
        done
        sleep 1
        pids=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
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

service_is_loaded() {
    launchctl list 2>/dev/null | grep -q "$SERVICE_LABEL"
}

install_and_start() {
    check_python
    echo "Installing $SERVICE_LABEL as a macOS LaunchAgent (always running)..."
    generate_plist

    if service_is_loaded; then
        echo "Unloading existing LaunchAgent..."
        launchctl unload -w "$PLIST_FILE" 2>/dev/null || true
    fi

    stop_manual_process_on_port

    echo "Loading and starting LaunchAgent..."
    launchctl load -w "$PLIST_FILE"

    echo "Waiting for service to start on http://127.0.0.1:$PORT..."
    local ready=0
    for _ in {1..15}; do
        if curl -s "http://127.0.0.1:$PORT/healthz" | grep -q '"ok":true'; then
            ready=1
            break
        fi
        sleep 0.5
    done

    if [ $ready -eq 1 ]; then
        echo "Service is running successfully!"
        echo "URL: http://127.0.0.1:$PORT"
        echo "Logs: $LOG_FILE"
        echo "LaunchAgent will automatically restart if killed and start on system boot/login."
    else
        echo "Warning: Service started but health check did not respond yet."
        echo "Check logs: tail -n 30 $LOG_FILE"
    fi
}

start_service() {
    check_python
    if [ ! -f "$PLIST_FILE" ]; then
        install_and_start
        return
    fi

    if ! service_is_loaded; then
        stop_manual_process_on_port
        launchctl load -w "$PLIST_FILE"
        echo "Service started."
    else
        echo "Service is already loaded. Checking if running..."
        status_service
    fi
}

stop_service() {
    if [ -f "$PLIST_FILE" ] && service_is_loaded; then
        echo "Stopping service $SERVICE_LABEL..."
        launchctl unload -w "$PLIST_FILE" 2>/dev/null || true
    fi
    stop_manual_process_on_port
    echo "Service stopped."
}

restart_service() {
    echo "Restarting $SERVICE_LABEL..."
    stop_service
    sleep 1
    start_service
}

status_service() {
    echo "=== Service Status for $SERVICE_LABEL ==="
    local loaded=0
    local pid=""
    if service_is_loaded; then
        loaded=1
        pid=$(launchctl list | grep "$SERVICE_LABEL" | awk '{print $1}')
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
    port_pids=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
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

uninstall_service() {
    echo "Uninstalling $SERVICE_LABEL..."
    stop_service
    if [ -f "$PLIST_FILE" ]; then
        rm -f "$PLIST_FILE"
        echo "Removed LaunchAgent plist: $PLIST_FILE"
    fi
    echo "Uninstallation complete."
}

show_logs() {
    touch "$LOG_FILE" "$ERR_LOG_FILE"
    echo "Streaming logs (Press Ctrl+C to exit)..."
    tail -n 50 -f "$LOG_FILE" "$ERR_LOG_FILE"
}

case "$1" in
    install)
        install_and_start
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        status_service
        ;;
    logs)
        show_logs
        ;;
    uninstall)
        uninstall_service
        ;;
    *)
        echo "Usage: $0 {install|start|stop|restart|status|logs|uninstall}"
        echo ""
        echo "Commands:"
        echo "  install    Generate LaunchAgent plist and start the service (always running)"
        echo "  start      Start the service"
        echo "  stop       Stop the service"
        echo "  restart    Restart the service"
        echo "  status     Check if service and port $PORT are active and healthy"
        echo "  logs       Stream live server logs"
        echo "  uninstall  Stop service and remove LaunchAgent plist"
        exit 1
        ;;
esac
