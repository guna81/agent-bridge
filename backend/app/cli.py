"""AgentBridge's local command-line service manager."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import signal
import shutil
import shlex
import tempfile
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import webbrowser

from cryptography.fernet import Fernet
import secrets

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("AGENTBRIDGE_HOME", Path.home() / ".agentbridge")).expanduser().resolve()
STATE = DATA / "service.json"
SECRETS = DATA / "secrets.json"
CONFIG = DATA / "config.json"
DEFAULT_PORT = 43187


def child_command(command):
    if FROZEN:
        return [sys.executable, command]
    return [sys.executable, "-m", "app.tray" if command == "_tray" else "app.cli", *([] if command == "_tray" else [command])]


def background_options():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    return {"start_new_session": True}


def terminate(pid):
    if os.name == "nt":
        import psutil
        try:
            process = psutil.Process(pid)
            for child in process.children(recursive=True):
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def credentials():
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not SECRETS.exists():
        values = {"secret_key": Fernet.generate_key().decode(), "key_pepper": secrets.token_urlsafe(32), "admin_token": secrets.token_urlsafe(32)}
        try:
            fd = os.open(SECRETS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as f:
                json.dump(values, f)
    return json.loads(SECRETS.read_text())


def identity(pid):
    import psutil
    try:
        process = psutil.Process(pid)
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        return f"process:{process.create_time()}:{process.exe()}"
    except (psutil.Error, OSError, TypeError):
        return None


def same_process(pid, expected):
    if not expected:
        return False
    if expected.startswith('process:'):
        return identity(pid) == expected
    if os.name == 'nt':
        current = identity(pid)
        return current is not None and current.removeprefix('process:') == expected
    # Older Unix installations recorded ps output; retain stop/upgrade compatibility.
    try:
        return subprocess.check_output(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='], text=True, stderr=subprocess.DEVNULL).strip() == expected
    except (OSError, subprocess.CalledProcessError, TypeError):
        return False


def state():
    try:
        value = json.loads(STATE.read_text())
        if same_process(value["pid"], value.get("identity")):
            return value
    except (OSError, ValueError, KeyError):
        pass
    return None


def healthy(port, token):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/admin/status-bar", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def start(args):
    if state():
        print("AgentBridge is already running. Use 'agentbridge status' for details.")
        return
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError as exc:
            raise RuntimeError(f"Port {args.port} is already in use; choose another with --port.") from exc
    values = credentials()
    if args.personal is None:
        try:
            args.personal = bool(json.loads(CONFIG.read_text()).get("personal", False))
        except (OSError, ValueError):
            args.personal = False
    env = os.environ.copy()
    env.update(PROXY_DATA_DIR=str(DATA), PROXY_HOST="127.0.0.1", PROXY_PORT=str(args.port),
               PROXY_SECRET_KEY=values["secret_key"], PROXY_KEY_PEPPER=values["key_pepper"],
               PROXY_ADMIN_TOKEN=values["admin_token"], PROXY_FRONTEND_DIST=str(ROOT / "frontend" / "dist"),
               PROXY_SINGLE_USER_PERSONAL_USE=str(args.personal).lower(),
               AGENTBRIDGE_SEED_PERSONAL=str(args.personal).lower())
    log = (DATA / "service.log").open("a")
    try:
        child = subprocess.Popen(child_command("_serve"), cwd=ROOT if FROZEN else ROOT / "backend", env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **background_options())
    finally:
        log.close()
    for _ in range(100):
        if child.poll() is not None:
            raise RuntimeError(f"Gateway failed to start. Check {DATA / 'service.log'}")
        if healthy(args.port, values["admin_token"]):
            break
        time.sleep(.1)
    else:
        child.terminate()
        child.wait(timeout=5)
        raise RuntimeError(f"Gateway did not become ready. Check {DATA / 'service.log'}")
    process_identity = identity(child.pid)
    if not process_identity:
        child.terminate()
        raise RuntimeError("Could not verify the gateway process; it was stopped.")
    info = {"pid": child.pid, "identity": process_identity, "port": args.port, "personal": args.personal}
    STATE.write_text(json.dumps(info))
    STATE.chmod(0o600)
    CONFIG.write_text(json.dumps({"personal": args.personal}))
    CONFIG.chmod(0o600)
    print(f"Gateway running at http://127.0.0.1:{args.port}")
    if args.personal:
        print("Personal CLI login reuse enabled for newly created providers.")
    if sys.platform == "darwin" and not args.no_tray:
        binary = ROOT / "menubar" / "LLMGatewayBar"
        if binary.exists():
            tray_env = env.copy()
            tray = subprocess.Popen([str(binary)], env=tray_env, cwd=ROOT, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            info.update(tray_pid=tray.pid, tray_identity=identity(tray.pid))
            STATE.write_text(json.dumps(info))
            print("Status bar started.")
        else:
            print("Status bar unavailable. Run ./menubar/build.sh to build it.")
    elif not args.no_tray:
        tray_log = (DATA / "tray.log").open("a")
        try:
            tray = subprocess.Popen(child_command("_tray"), env=env, cwd=ROOT if FROZEN else ROOT / "backend",
                                    stdin=subprocess.DEVNULL, stdout=tray_log, stderr=subprocess.STDOUT,
                                    **background_options())
        finally:
            tray_log.close()
        time.sleep(1)
        if tray.poll() is None and identity(tray.pid):
            info.update(tray_pid=tray.pid, tray_identity=identity(tray.pid))
            STATE.write_text(json.dumps(info))
            print("System tray helper started.")
        else:
            print(f"System tray unavailable. Check {DATA / 'tray.log'}; the gateway is still running.")
    print("Run 'agentbridge dashboard' to open the dashboard.")


def stop():
    info = state()
    if not info:
        print("AgentBridge is not running under this CLI.")
        return
    if same_process(info.get("tray_pid"), info.get("tray_identity")):
        terminate(info["tray_pid"])
    terminate(info["pid"])
    for _ in range(50):
        if not same_process(info["pid"], info["identity"]):
            break
        time.sleep(.1)
    else:
        raise RuntimeError("Gateway did not stop; its process is still running.")
    STATE.unlink(missing_ok=True)
    print("AgentBridge stopped.")


def update_cli():
    from app.updates import check_update
    if not FROZEN:
        raise RuntimeError("This is a source checkout. Update it with git and rebuild; agentbridge update is for release installations.")
    result = check_update(DATA, force=True)
    if not result["latest"]:
        raise RuntimeError("Could not find a stable release. Check your connection or try again after a release is published.")
    if not result["available"]:
        print(f"AgentBridge {result['current']} is already up to date (latest: {result['latest']}).")
        return

    # Only replace a launcher that points to the currently running installation.
    install_root = Path(os.environ.get("AGENTBRIDGE_INSTALL_ROOT", Path(os.environ.get("LOCALAPPDATA", "")) / "AgentBridge" if os.name == "nt" else Path.home() / ".local/share/agentbridge")).expanduser()
    bin_dir = Path(os.environ.get("AGENTBRIDGE_BIN_DIR", install_root / "bin" if os.name == "nt" else Path.home() / ".local/bin")).expanduser()
    launcher = bin_dir / ("agentbridge.cmd" if os.name == "nt" else "agentbridge")
    try:
        managed = str(Path(sys.executable).resolve()).lower() in launcher.read_text(encoding="utf-8").lower() if os.name == "nt" else launcher.is_symlink() and launcher.resolve() == Path(sys.executable).resolve()
    except (OSError, UnicodeError):
        managed = False
    if not managed:
        raise RuntimeError("The current executable is not linked to the expected installer launcher. Set AGENTBRIDGE_INSTALL_ROOT and AGENTBRIDGE_BIN_DIR to the original install locations, or rerun the installer manually.")
    script = ROOT / "installer" / ("install.ps1" if os.name == "nt" else "install.sh")
    if not script.is_file():
        raise RuntimeError("This installation does not contain the updater. Rerun the installer manually to upgrade it.")
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)] if os.name == "nt" else ["sh", str(script)]
    print(f"Installing AgentBridge {result['latest']}…", flush=True)
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError("Update failed. Your existing installation and data were retained; see the installer output above.")
    if state():
        print("The gateway is still running the previous version. Run 'agentbridge stop' and 'agentbridge start' to use the update.")
    else:
        print("Update installed. Run 'agentbridge start' when ready.")


def installation_paths():
    install_root = Path(os.environ.get("AGENTBRIDGE_INSTALL_ROOT", Path(os.environ.get("LOCALAPPDATA", "")) / "AgentBridge" if os.name == "nt" else Path.home() / ".local/share/agentbridge")).expanduser().resolve()
    bin_dir = Path(os.environ.get("AGENTBRIDGE_BIN_DIR", install_root / "bin" if os.name == "nt" else Path.home() / ".local/bin")).expanduser().resolve()
    return install_root, bin_dir / ("agentbridge.cmd" if os.name == "nt" else "agentbridge")


def uninstall_cli(purge=False):
    install_root, launcher = installation_paths()
    executable = Path(sys.executable).resolve()
    try:
        if FROZEN:
            if os.name == "nt":
                managed = f'"{executable}" %*'.lower() in launcher.read_text(encoding="utf-8").lower()
            else:
                managed = launcher.is_symlink() and launcher.resolve() == executable
            # Never remove release directories for a manually extracted package.
            release_dir = executable.parent.parent
            managed = managed and executable.parent.name == "agentbridge" and release_dir.parent == install_root / "releases" and (release_dir.name.startswith("release.") or release_dir.name.startswith("release-"))
        elif os.name == "nt":
            content = launcher.read_text(encoding="utf-8").lower()
            managed = f'"{executable}" -m app.cli %*'.lower() in content and str(ROOT / "backend").lower() in content
        else:
            managed = not launcher.is_symlink() and launcher.read_text() == '#!/bin/sh\nexec ' + shlex.quote(str(ROOT / 'agentbridge')) + ' "$@"\n'
    except (OSError, UnicodeError):
        managed = False
    if not managed:
        raise RuntimeError("Could not verify an installer-managed launcher for this installation. Set AGENTBRIDGE_INSTALL_ROOT and AGENTBRIDGE_BIN_DIR to the original locations, or remove it manually.")

    if purge and DATA.exists():
        # A custom AGENTBRIDGE_HOME must contain our credentials, and must not
        # encompass a home, checkout, launcher, or installation directory.
        protected = [Path.home().resolve(), ROOT.resolve(), install_root, launcher.parent]
        if any(path == DATA or path.is_relative_to(DATA) for path in protected):
            raise RuntimeError("Refusing to remove an unsafe AgentBridge data directory.")
        try:
            values = json.loads((DATA / "secrets.json").read_text())
            if not all(isinstance(values.get(k), str) and values[k] for k in ("secret_key", "key_pepper", "admin_token")):
                raise ValueError("invalid credentials")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError("Cannot verify the AgentBridge data directory; remove it manually if appropriate.") from exc

    release_dirs = []
    releases = install_root / "releases"
    if FROZEN and releases.is_dir() and not releases.is_symlink():
        binary_name = "agentbridge.exe" if os.name == "nt" else "agentbridge"
        release_dirs = [path for path in releases.iterdir() if not path.is_symlink() and path.is_dir()
                        and (path.name.startswith("release.") or path.name.startswith("release-"))
                        and (path / "agentbridge" / binary_name).is_file()]
    stop()
    if os.name == "nt" and FROZEN:
        # Windows cannot delete the executable while this process is running.
        # A detached PowerShell process waits for it to exit before removing files.
        def ps_quote(path):
            return "'" + str(path).replace("'", "''") + "'"
        log = Path(tempfile.gettempdir()) / f"agentbridge-uninstall-{os.getpid()}.log"
        paths = [launcher, *release_dirs, *([DATA] if purge and DATA.exists() else [])]
        path_array = ",".join(ps_quote(path) for path in paths)
        script = (f"$ErrorActionPreference='Stop'; try {{ Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
                  f"foreach ($p in @({path_array})) {{ for ($i=0; $i -lt 15; $i++) {{ "
                  f"if (-not (Test-Path -LiteralPath $p)) {{ break }}; "
                  f"try {{ Remove-Item -LiteralPath $p -Force -Recurse; break }} catch {{ if ($i -eq 14) {{ throw }}; Start-Sleep -Seconds 1 }} }} }}; "
                  f"'Uninstall complete' | Set-Content -LiteralPath {ps_quote(log)} }} "
                  f"catch {{ $_ | Out-String | Set-Content -LiteralPath {ps_quote(log)}; exit 1 }}")
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                         cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **background_options())
        print(f"Uninstall scheduled after this command exits. Check {log} for the result.")
    else:
        launcher.unlink()
        for path in release_dirs:
            shutil.rmtree(path)
        if purge and DATA.exists():
            shutil.rmtree(DATA)
        print("AgentBridge uninstalled.")
    if not purge:
        print(f"User data retained at {DATA}. Use --purge during uninstall to remove it.")
    if not FROZEN:
        print(f"Source checkout retained at {ROOT}.")


def main():
    parser = argparse.ArgumentParser(
        prog="agentbridge",
        description="Run a local AI gateway and monitor subscription usage in your menu bar or system tray.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Quick start:
  agentbridge start --personal   Start with your own CLI logins
  agentbridge dashboard          Open the signed-in dashboard
  agentbridge status             Check whether the gateway is running

Use 'agentbridge COMMAND --help' for details and examples.
Data and credentials are stored in ~/.agentbridge (override with AGENTBRIDGE_HOME).
Documentation: https://github.com/guna81/agent-bridge#readme""",
    )
    from app.updates import VERSION, check_update
    parser.add_argument("--version", action="version", version=f"AgentBridge {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True, title="commands",
                                metavar="{start,stop,status,dashboard,update,uninstall}")
    start_parser = sub.add_parser("start", help="start the gateway and status indicator",
        description="Start the local gateway and menu bar or system tray indicator in the background.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  agentbridge start --personal
  agentbridge start --api-key-mode
  agentbridge start --port 43188 --no-tray

If no authentication mode is specified, the last saved mode is used.
The gateway listens on 127.0.0.1. Install and sign in to provider CLIs separately.""")
    start_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"local gateway port (default: {DEFAULT_PORT})")
    mode = start_parser.add_mutually_exclusive_group()
    mode.add_argument("--personal", dest="personal", action="store_true", default=None, help="reuse your own CLI logins for personal use; enable newly created providers")
    mode.add_argument("--api-key-mode", dest="personal", action="store_false", help="disable reuse of local CLI logins")
    start_parser.add_argument("--no-tray", action="store_true", help="start the gateway without a menu bar or tray indicator")
    sub.add_parser("stop", help="stop the managed gateway and indicator",
                   description="Stop the gateway and status indicator started by this CLI. User data is retained.")
    sub.add_parser("status", help="show the gateway's health and address",
                   description="Show whether the managed gateway is running, its health, address, and process ID.")
    sub.add_parser("update", help="install the latest stable release",
        description="Check for and install a newer stable release for an installer-managed package.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""A running gateway keeps using the old version until restarted:
  agentbridge stop
  agentbridge start

Source checkouts are updated with Git and rebuilt instead.""")
    uninstall_parser = sub.add_parser("uninstall", help="remove the installed CLI and stop its gateway",
        description="Stop the managed gateway and remove the verified launcher and installed release files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""User data is kept by default. A source checkout and launcher backups are retained.
On Windows, packaged removal completes after this command exits; check the printed log.

Examples:
  agentbridge uninstall           Keep settings, credentials, and database
  agentbridge uninstall --purge   Delete those user data files as well""")
    uninstall_parser.add_argument("--purge", action="store_true", help="also delete AgentBridge settings, credentials, and database")
    dashboard_parser = sub.add_parser("dashboard", help="open the signed-in dashboard",
        description="Open the dashboard in your browser and sign in using the local admin token. Start the gateway first.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  agentbridge dashboard
  agentbridge dashboard --show-token

Treat the admin token as a secret. --show-token prints it for manual sign-in.""")
    dashboard_parser.add_argument("--show-token", action="store_true", help="print the admin token for manual sign-in")
    # Internal subprocess commands remain callable but are omitted from public help.
    sub.add_parser("_serve")
    sub.add_parser("_tray")
    args = parser.parse_args()
    if args.command not in ("_serve", "_tray", "update", "uninstall"):
        update = check_update(DATA)
        if update["available"]:
            print(f"Update available: AgentBridge {update['current']} → {update['latest']}. "
                  "Run 'agentbridge update' to install it.", file=sys.stderr)
    try:
        if args.command == "start":
            if not 1 <= args.port <= 65535:
                parser.error("port must be between 1 and 65535")
            start(args)
        elif args.command == "stop":
            stop()
        elif args.command == "status":
            info = state()
            if info:
                print(f"Gateway: {'ready' if healthy(info['port'], credentials()['admin_token']) else 'not responding'} at http://127.0.0.1:{info['port']} (PID {info['pid']})")
            else:
                print("AgentBridge is not running under this CLI.")
        elif args.command == "update":
            update_cli()
        elif args.command == "uninstall":
            uninstall_cli(purge=args.purge)
        elif args.command == "dashboard":
            info = state()
            if not info:
                raise RuntimeError("Start AgentBridge first with 'agentbridge start'.")
            print(f"Dashboard: http://127.0.0.1:{info['port']}")
            token = credentials()['admin_token']
            if args.show_token:
                print(f"Admin token: {token}")
            url = f"http://127.0.0.1:{info['port']}/#admin_token={urllib.parse.quote(token, safe='')}"
            if not webbrowser.open(url):
                raise RuntimeError("Could not open a browser. Run 'agentbridge dashboard --show-token' to sign in manually.")
        elif args.command == "_tray":
            from app.tray import Tray
            Tray().run()
        else:
            import uvicorn
            from app.config import get_settings
            s = get_settings()
            uvicorn.run("app.main:app", host=s.host, port=s.port)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
