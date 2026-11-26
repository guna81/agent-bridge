#!/usr/bin/env bash
# Full-stack dev mode: the gateway restarts when backend code changes and the
# dashboard hot-reloads when frontend code changes. Ctrl+C stops both.
#
#   ./scripts/dev.sh            # gateway on PROXY_PORT from backend/.env (default 8000), UI on :5173
#   UI_PORT=5174 ./scripts/dev.sh
#   NO_OPEN=1 ./scripts/dev.sh  # don't open the browser
#
# Uses backend/.env and backend/data, so it never touches an installed AgentBridge's settings or database.
# Skills and instructions are the exception: both always use ~/.agentbridge/agents.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
py="$root/backend/.venv/bin/python"
[ -x "$py" ] || { echo "No backend venv. Run: (cd backend && uv sync --python 3.12 --all-extras)" >&2; exit 1; }
[ -d "$root/frontend/node_modules" ] || { echo "No frontend deps. Run: (cd frontend && npm install)" >&2; exit 1; }

env_port="$(grep -E '^PROXY_PORT=' "$root/backend/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '"'"'"' ' || true)"
port="${PROXY_PORT:-${env_port:-8000}}"
ui_port="${UI_PORT:-5173}"

if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $port is already in use. Stop that process or set PROXY_PORT to a free port." >&2
  exit 1
fi

pids=()
# Stop everything this script started, including uvicorn's reloader worker and Vite's children.
# Not `kill 0`: when started from make, npm or an IDE task the process group is the caller's too.
descendants() { local c; for c in $(pgrep -P "$1"); do echo "$c"; descendants "$c"; done; }
cleanup() {
  trap - INT TERM EXIT
  local all
  all="$(descendants $$)"  # collect the whole tree first; killing a parent orphans its children
  [ -n "$all" ] && kill $all 2>/dev/null
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# A stray VIRTUAL_ENV from another project confuses tools that look at it.
unset VIRTUAL_ENV

(cd "$root/backend" && exec "$py" -m uvicorn app.main:app --reload --reload-dir app \
  --host 127.0.0.1 --port "$port" --proxy-headers 2>&1 | sed -u 's/^/[api] /') &
pids+=($!)

(cd "$root/frontend" && VITE_BACKEND="http://127.0.0.1:$port" exec npm run dev -- --port "$ui_port" --strictPort 2>&1 | sed -u 's/^/[ui]  /') &
pids+=($!)

echo "Dashboard (hot reload): http://localhost:$ui_port   API: http://127.0.0.1:$port"

# Open the dashboard already signed in, like `agentbridge dashboard`. The token rides in the URL
# fragment, which the browser never sends to a server; the dashboard strips it on load.
# Set NO_OPEN=1 to skip.
admin_token() {
  local t="${PROXY_ADMIN_TOKEN:-}"
  [ -n "$t" ] || t="$(grep -E '^PROXY_ADMIN_TOKEN=' "$root/backend/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)"
  [ -n "$t" ] || t="$(tr -d '[:space:]' < "$root/backend/data/admin_token" 2>/dev/null || true)"
  printf '%s' "$t"
}
if [ -z "${NO_OPEN:-}" ]; then
  (
    for _ in $(seq 1 60); do
      [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$ui_port/admin/settings")" = 401 ] && break
      sleep 1
    done
    token="$(admin_token)"
    url="http://localhost:$ui_port/"
    [ -n "$token" ] && url="$url#admin_token=$token"
    if command -v open >/dev/null; then open "$url"; elif command -v xdg-open >/dev/null; then xdg-open "$url" >/dev/null 2>&1; fi
    [ -n "$token" ] && echo "Opened the dashboard signed in." || echo "Opened the dashboard. No admin token found; set PROXY_ADMIN_TOKEN in backend/.env."
  ) &
fi

# Stop everything if either side exits.
while :; do
  for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null || exit 1; done
  sleep 1
done
