"""AgentBridge's local command-line service manager."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
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


def main():
    parser = argparse.ArgumentParser(prog="agentbridge", description="Run the local AgentBridge gateway and status bar")
    sub = parser.add_subparsers(dest="command", required=True)
    start_parser = sub.add_parser("start", help="start the gateway and system tray")
    start_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"gateway port (default: {DEFAULT_PORT})")
    mode = start_parser.add_mutually_exclusive_group()
    mode.add_argument("--personal", dest="personal", action="store_true", default=None, help="allow reuse of your own CLI logins for personal use")
    mode.add_argument("--api-key-mode", dest="personal", action="store_false", help="disable personal CLI login reuse")
    start_parser.add_argument("--no-tray", action="store_true")
    for name in ("stop", "status", "_serve", "_tray"):
        sub.add_parser(name)
    dashboard_parser = sub.add_parser("dashboard", help="open the signed-in dashboard")
    dashboard_parser.add_argument("--show-token", action="store_true", help="print the admin token for manual sign-in")
    args = parser.parse_args()
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
