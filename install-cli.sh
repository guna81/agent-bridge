#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null || { echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }
command -v npm >/dev/null && command -v node >/dev/null || { echo 'Install Node.js and npm first.' >&2; exit 1; }
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)) process.exit(1)' || { echo 'Node.js 20.19+ or 22.12+ is required (Node 21 is not supported).' >&2; exit 1; }
(cd "$ROOT_DIR/backend" && uv sync --python 3.12 --inexact)
(cd "$ROOT_DIR/frontend" && npm ci && npm run build)
if [[ "$(uname -s)" == Darwin ]]; then
  "$ROOT_DIR/menubar/build.sh"
fi
INSTALL_DIR="${AGENTBRIDGE_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$INSTALL_DIR"
# A wrapper preserves the checkout path; keep this checkout after installation.
ROOT_DIR="$ROOT_DIR" INSTALL_DIR="$INSTALL_DIR" python3 - <<'PY'
import os, pathlib, shlex
root = pathlib.Path(os.environ['ROOT_DIR'])
target = pathlib.Path(os.environ['INSTALL_DIR']) / 'agentbridge'
if target.exists() or target.is_symlink():
    raise SystemExit(f'{target} already exists; remove it or choose AGENTBRIDGE_BIN_DIR before installing.')
target.write_text('#!/bin/sh\nexec ' + shlex.quote(str(root / 'agentbridge')) + ' "$@"\n')
target.chmod(0o755)
PY
printf '\nInstalled %s/agentbridge. Keep this checkout in place.\n' "$INSTALL_DIR"
printf 'Run: agentbridge start\n'
printf 'If the command is not found, add %s to your PATH.\n' "$INSTALL_DIR"
