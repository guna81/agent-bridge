# Command line

The `agentbridge` command manages the gateway and indicator.

| Command | What it does |
|---|---|
| `agentbridge start` | Start the gateway and status indicator |
| `agentbridge start --port 43188` | Start on another port (the port is remembered) |
| `agentbridge start --no-tray` | Run the gateway without a menu bar or tray indicator |
| `agentbridge stop` | Stop the managed gateway and indicator |
| `agentbridge status` | Show gateway health and address |
| `agentbridge dashboard` | Open the signed-in dashboard |
| `agentbridge dashboard --show-token` | Print the admin token for manual sign-in |
| `agentbridge autostart status` | Check startup at user login |
| `agentbridge autostart enable` | Start automatically when you sign in |
| `agentbridge autostart disable` | Turn automatic startup off |
| `agentbridge update` | Install the latest stable release |
| `agentbridge uninstall` | Stop and remove the install, keeping user data |
| `agentbridge uninstall --purge` | Also remove settings, credentials and database |
| `agentbridge --version` | Show the installed version |

## Defaults

- **Port:** `43187`, bound to loopback (`127.0.0.1`) only. A custom `--port` is remembered.
- **Data and logs:** `~/.agentbridge` (override with `AGENTBRIDGE_HOME`). It holds the database, secrets and logs.

!!! tip
    Starting again is safe: `agentbridge start` restarts a missing indicator helper without restarting the gateway, and doesn't duplicate it.

## Autostart

After the first successful start, AgentBridge enables startup at user login when it can verify the installed launcher.

| OS | Mechanism |
|---|---|
| macOS | LaunchAgent |
| Linux | XDG autostart `.desktop` file (needs a desktop session that supports it; tray support varies) |
| Windows | Startup entry |

Use `agentbridge autostart disable` to turn it off. Login-start problems are logged in `~/.agentbridge/autostart.log`.

## Updating

After `agentbridge update`, run `agentbridge stop` then `agentbridge start` to use the new version. Updates keep user data.

## Environment variables

| Variable | Purpose |
|---|---|
| `AGENTBRIDGE_HOME` | Data directory (default `~/.agentbridge`) |
| `AGENTBRIDGE_DISABLE_AUTOSTART` | Don't enable login startup |
| `AGENTBRIDGE_LEGACY_SERVICE=1` | Keep the legacy source service manager (don't combine with autostart for the same gateway) |

See [Configuration](configuration.md) for server settings.
