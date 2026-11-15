# Install

Prebuilt packages include the CLI and the dashboard. You do not need Python or Node.js.

## One-line install

=== "macOS / Linux"

    ```sh
    curl -fsSL https://raw.githubusercontent.com/guna81/agent-bridge/main/install.sh | sh
    ```

    Supported: macOS on Apple Silicon, and Linux x86-64 (glibc, Ubuntu 22.04 or newer; the tray needs an X11 desktop).

    Make sure `~/.local/bin` is on your `PATH`.

=== "Windows (PowerShell)"

    ```powershell
    irm https://raw.githubusercontent.com/guna81/agent-bridge/main/install.ps1 | iex
    ```

    Supported: Windows x86-64. Open a new terminal after installing.

The installers download the [latest release](https://github.com/guna81/agent-bridge/releases/latest) and verify its SHA-256 checksum. The launcher is placed in `~/.local/bin/agentbridge` and release files in `~/.local/share/agentbridge/releases`.

!!! note "About trust"
    The checksum catches download errors, but it comes from the same release as the archive, so it does not independently prove who published it. Binaries are unsigned. If you prefer, download the install script, read it, then run it locally.

### Installer options

| Variable | Purpose |
|---|---|
| `AGENTBRIDGE_INSTALL_ROOT` | Where release files are installed |
| `AGENTBRIDGE_BIN_DIR` | Where the `agentbridge` launcher is placed |
| `AGENTBRIDGE_REPOSITORY` | Install from a fork (`owner/repo`) |
| `AGENTBRIDGE_RELEASE_BASE_URL` | Alternative release download location |
| `AGENTBRIDGE_DISABLE_AUTOSTART` | Don't enable startup at login |

If you install to a custom location, use the same `AGENTBRIDGE_INSTALL_ROOT` and `AGENTBRIDGE_BIN_DIR` when you uninstall.

## Verify

```sh
agentbridge --version
```

## Install the agent CLIs

AgentBridge uses the agent CLIs you already have. Install and sign in to the ones you want separately (for example `claude`, `codex`, `agy`, `gemini`). Available usage data depends on the provider and platform.

## Install from source

For development you need Python 3.12 (via [uv](https://docs.astral.sh/uv/)) and Node.js 20.19+ or 22.12+ (Node 21 is not supported).

```sh
git clone https://github.com/guna81/agent-bridge.git
cd agent-bridge
./install-cli.sh        # on Windows: ./install-cli.ps1
agentbridge start
agentbridge dashboard
```

Follow the PATH instructions the script prints and keep the checkout in place: the installed command uses its Python environment and built dashboard. `agentbridge update` is only for packaged installs; update a source checkout with Git and rebuild.

## Update and uninstall

```sh
agentbridge update          # install the latest stable release
agentbridge stop && agentbridge start   # run the new version

agentbridge uninstall            # remove the install, keep your data
agentbridge uninstall --purge    # also delete settings, credentials and database
```

Updates keep existing installation files and user data. On Windows the packaged uninstall finishes after the command exits and prints a log path.
