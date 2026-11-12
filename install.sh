#!/bin/sh
# Install the latest published AgentBridge release into the current user's account.
set -eu
repo=${AGENTBRIDGE_REPOSITORY:-guna81/agent-bridge}
base=${AGENTBRIDGE_RELEASE_BASE_URL:-https://github.com/$repo/releases/latest/download}
case "$(uname -s):$(uname -m)" in
  Darwin:arm64) platform=macos-arm64 ;;
  Linux:x86_64|Linux:amd64) platform=linux-x86_64 ;;
  *) echo 'No release package is available for this OS and architecture.' >&2; exit 1 ;;
esac
command -v curl >/dev/null 2>&1 || { echo 'curl is required.' >&2; exit 1; }
name="agentbridge-$platform.tar.gz"
work=$(mktemp -d "${TMPDIR:-/tmp}/agentbridge-install.XXXXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
curl -fL --retry 3 -o "$work/$name" "$base/$name"
curl -fL --retry 3 -o "$work/$name.sha256" "$base/$name.sha256"
expected=$(awk 'NR == 1 {print $1}' "$work/$name.sha256")
case "$expected" in *[!0-9a-fA-F]*|'') echo 'Invalid checksum file.' >&2; exit 1 ;; esac
[ "${#expected}" -eq 64 ] || { echo 'Invalid checksum length.' >&2; exit 1; }
if command -v shasum >/dev/null 2>&1; then actual=$(shasum -a 256 "$work/$name" | awk '{print $1}')
elif command -v sha256sum >/dev/null 2>&1; then actual=$(sha256sum "$work/$name" | awk '{print $1}')
else echo 'shasum or sha256sum is required.' >&2; exit 1; fi
[ "$actual" = "$expected" ] || { echo 'Checksum verification failed.' >&2; exit 1; }
mkdir -p "$work/unpack"
tar -xzf "$work/$name" -C "$work/unpack"
[ -x "$work/unpack/agentbridge/agentbridge" ] || { echo 'Invalid release archive.' >&2; exit 1; }
install_root=${AGENTBRIDGE_INSTALL_ROOT:-$HOME/.local/share/agentbridge}
bin=${AGENTBRIDGE_BIN_DIR:-$HOME/.local/bin}
mkdir -p "$install_root/releases" "$bin"
release=$(mktemp -d "$install_root/releases/release.XXXXXXXX")
mv "$work/unpack/agentbridge" "$release/agentbridge"
# Preserve any existing command instead of deleting it during an upgrade.
if [ -e "$bin/agentbridge" ] || [ -L "$bin/agentbridge" ]; then
  backup=$(mktemp "$bin/agentbridge.backup.XXXXXXXX")
  rm -f "$backup"
  mv "$bin/agentbridge" "$backup"
  echo "Previous command saved as $backup"
fi
ln -s "$release/agentbridge/agentbridge" "$bin/agentbridge"
echo "Installed AgentBridge to $bin/agentbridge"
echo 'Run: agentbridge start --personal'
echo 'Then: agentbridge dashboard'
echo "Ensure $bin is on your PATH. Existing gateways can be stopped with agentbridge stop."
