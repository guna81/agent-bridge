"""User-login startup for the AgentBridge CLI."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

NAME = 'AgentBridge'
LABEL = 'com.agentbridge.autostart'
GENERATION = 'AGENTBRIDGE_AUTOSTART_GENERATION'


def startup_environment(data_dir: Path):
    env = {'AGENTBRIDGE_HOME': str(data_dir)}
    for key in ('AGENTBRIDGE_INSTALL_ROOT', 'AGENTBRIDGE_BIN_DIR'):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def desktop_quote(value: str) -> str:
    # Desktop Entry Exec values require double-quoted strings and escaped field codes.
    return '"' + value.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$') + '"'


def register(launcher: Path, data_dir: Path, *, enable_disabled=False):
    launcher = launcher.absolute()  # Preserve the installer symlink across upgrades.
    if not launcher.is_file():
        raise RuntimeError('The installed AgentBridge launcher could not be found.')
    env = startup_environment(data_dir)
    if sys.platform == 'darwin':
        folder = Path.home() / 'Library/LaunchAgents'
        folder.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        path = folder / f'{LABEL}.plist'
        if path.exists() and not enable_disabled:
            try:
                with path.open('rb') as stream:
                    owner = plistlib.load(stream).get('EnvironmentVariables', {}).get('AGENTBRIDGE_HOME')
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                raise RuntimeError('Cannot inspect existing LaunchAgent; use autostart enable to replace it') from exc
            if owner and owner != str(data_dir):
                raise RuntimeError('LaunchAgent belongs to another data directory; use autostart enable to replace it')
        plist = {'Label': LABEL, 'ProgramArguments': [str(launcher), 'start'], 'RunAtLoad': True,
                 'EnvironmentVariables': {**env, 'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')},
                 'StandardOutPath': str(data_dir / 'autostart.log'), 'StandardErrorPath': str(data_dir / 'autostart.log')}
        # launchctl retains the old environment until a job is reloaded. A stable
        # fingerprint lets status distinguish that job from the plist on disk.
        plist['EnvironmentVariables'][GENERATION] = hashlib.sha256(plistlib.dumps(plist)).hexdigest()
        with path.open('wb') as stream:
            plistlib.dump(plist, stream)
        domain = f'gui/{os.getuid()}'
        service = f'{domain}/{LABEL}'
        if enable_disabled:
            result = subprocess.run(['launchctl', 'enable', service], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f'Could not enable LaunchAgent: {result.stderr.strip()}')
        elif macos_disabled(domain):
            raise RuntimeError("LaunchAgent is disabled in macOS; run 'agentbridge autostart enable' to enable it")
        loaded = subprocess.run(['launchctl', 'print', service], capture_output=True, text=True)
        if not loaded.returncode:
            # Never boot out a running job: this command may itself be that job.
            # An unknown state is also unsafe; the saved plist applies at next login.
            if not macos_job_idle(loaded.stdout):
                raise RuntimeError('LaunchAgent saved but reload deferred because the job may be running; it will be applied at next login')
            result = subprocess.run(['launchctl', 'bootout', service], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f'LaunchAgent saved but could not be unloaded: {result.stderr.strip()}')
        result = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'LaunchAgent saved but could not be loaded: {result.stderr.strip()}')
    elif sys.platform.startswith('linux'):
        folder = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'autostart'
        folder.mkdir(parents=True, exist_ok=True)
        command = ['/usr/bin/env', *(f'{k}={v}' for k, v in env.items()), str(launcher), 'start']
        path = folder / 'agentbridge.desktop'
        path.write_text('[Desktop Entry]\nType=Application\nName=AgentBridge\nComment=Start the AgentBridge gateway and usage indicator\nExec=' + ' '.join(desktop_quote(x) for x in command) + '\nTerminal=false\nX-GNOME-Autostart-enabled=true\n', encoding='utf-8')
    elif sys.platform == 'win32':
        import winreg
        # A per-user Run entry avoids administrator privileges and runs at sign-in.
        data_dir.mkdir(parents=True, exist_ok=True)
        script = data_dir / 'autostart.cmd'
        lines = ['@echo off', *(f'set "{k}={v}"' for k, v in env.items()), f'call "{launcher}" start']
        if any('\n' in line or '\r' in line or '%' in line for line in lines):
            raise RuntimeError('Autostart paths may not contain percent signs or line breaks on Windows.')
        script.write_text('\r\n'.join(lines) + '\r\n', encoding='utf-8')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, f'cmd.exe /d /c ""{script}""')
    else:
        raise RuntimeError('Automatic startup is not supported on this platform.')


def unregister(data_dir: Path):
    if sys.platform == 'darwin':
        path = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
        if macos_plist(data_dir) is not None:
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            path.unlink(missing_ok=True)
    elif not is_registered(data_dir):
        return
    elif sys.platform.startswith('linux'):
        (Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'autostart/agentbridge.desktop').unlink(missing_ok=True)
    elif sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, NAME)
        except FileNotFoundError:
            pass
        (data_dir / 'autostart.cmd').unlink(missing_ok=True)
    else:
        raise RuntimeError('Automatic startup is not supported on this platform.')


def macos_plist(data_dir: Path):
    path = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
    try:
        with path.open('rb') as stream:
            plist = plistlib.load(stream)
        if plist.get('EnvironmentVariables', {}).get('AGENTBRIDGE_HOME') == str(data_dir):
            return plist
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def macos_job_idle(output):
    # launchctl prints nested structures with greater indentation; their states
    # (for example, an active endpoint) are not the service's process state.
    fields = re.findall(r'^([ \t]+)([\w-]+)[ \t]*=[ \t]*(.*?)[ \t]*$', output, re.MULTILINE)
    if not fields:
        return False
    depth = min(len(indent.expandtabs(8)) for indent, _, _ in fields)
    top = [(key, value) for indent, key, value in fields if len(indent.expandtabs(8)) == depth]
    states = [value for key, value in top if key == 'state']
    return states in (['waiting'], ['exited'], ['not running']) and not any(key == 'pid' for key, _ in top)


def macos_last_failure():
    """Return the last nonzero launch exit code, if launchd reports one."""
    if sys.platform != 'darwin':
        return None
    try:
        result = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/{LABEL}'], capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode:
        return None
    match = re.search(r'^\tlast exit code\s*=\s*(\d+)\s*$', result.stdout, re.MULTILINE)
    if not match:
        return None
    code = int(match.group(1))
    return code if code else None


def macos_disabled(domain):
    result = subprocess.run(['launchctl', 'print-disabled', domain], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Could not check LaunchAgent status: {result.stderr.strip()}')
    return bool(re.search(r'"' + re.escape(LABEL) + r'"\s*=>\s*(?:disabled|true)\b', result.stdout))


def is_registered(data_dir: Path):
    if sys.platform == 'darwin':
        plist = macos_plist(data_dir)
        if plist is None:
            return False
        args = plist.get('ProgramArguments')
        if not isinstance(args, list) or len(args) != 2 or args[1] != 'start' or not isinstance(args[0], str) or not Path(args[0]).is_file() or not plist.get('RunAtLoad'):
            return False
        domain = f'gui/{os.getuid()}'
        try:
            if macos_disabled(domain):
                return False
            loaded = subprocess.run(['launchctl', 'print', f'{domain}/{LABEL}'], capture_output=True, text=True)
            if loaded.returncode:
                return False
            generation = plist.get('EnvironmentVariables', {}).get(GENERATION)
            if generation is not None:
                if not isinstance(generation, str) or not re.search(
                    r'^\s*"?' + re.escape(GENERATION) + r'"?\s*=>\s*"?' + re.escape(generation) + r'"?\s*$',
                    loaded.stdout, re.MULTILINE,
                ):
                    return False
            return True
        except (OSError, RuntimeError):
            return False
    if sys.platform.startswith('linux'):
        path = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'autostart/agentbridge.desktop'
        try:
            return desktop_quote(f'AGENTBRIDGE_HOME={data_dir}') in path.read_text(encoding='utf-8')
        except OSError:
            return False
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                value, _ = winreg.QueryValueEx(key, NAME)
            return str(data_dir / 'autostart.cmd').lower() in value.lower()
        except FileNotFoundError:
            return False
    return False
