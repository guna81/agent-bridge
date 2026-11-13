import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace


def test_cli_start_and_stop(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    # The managed service must not seed the integration suite's shared database.
    for key in ('PROXY_DATABASE_URL', 'PROXY_QUEUE_BACKEND', 'PROXY_REDIS_URL'):
        env.pop(key, None)
    env['AGENTBRIDGE_HOME'] = str(tmp_path)
    (tmp_path / 'update-check.json').write_text(json.dumps({'checked_at': __import__('time').time(), 'latest': None}))
    # Old API-key-only settings must not keep CLI logins disabled after upgrading.
    (tmp_path / 'config.json').write_text(json.dumps({'personal': False}))
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    command = [sys.executable, '-m', 'app.cli']
    def run(*args):
        return subprocess.run([*command, *args], env=env, capture_output=True, text=True, timeout=20)
    try:
        started = run('start', '--no-tray', '--port', str(port))
        assert started.returncode == 0, started.stderr
        assert 'ready' in run('status').stdout
        assert 'personal' not in json.loads((tmp_path / 'config.json').read_text())
        assert 'Provider API keys and personal CLI logins are available' in started.stdout
        occupied = run('start', '--port', str(port))
        assert 'already running' in occupied.stdout
        assert run('stop').returncode == 0
        assert 'not running' in run('status').stdout
        restarted = run('start', '--no-tray')
        assert restarted.returncode == 0, restarted.stderr
        assert json.loads((tmp_path / 'service.json').read_text())['port'] == port
        assert 'Provider API keys and personal CLI logins are available' in restarted.stdout
    finally:
        run('stop')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_running_gateway_repairs_missing_helper_and_autostart(tmp_path, monkeypatch, capsys):
    from app import autostart, cli
    info = {'pid': 101, 'identity': 'gateway', 'port': 43210}
    launcher = tmp_path / 'agentbridge'
    binary = tmp_path / 'menubar' / 'LLMGatewayBar'
    binary.parent.mkdir()
    binary.touch()
    calls = []
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    monkeypatch.setattr(cli, 'DATA', tmp_path)
    monkeypatch.setattr(cli, 'STATE', tmp_path / 'service.json')
    monkeypatch.setattr(cli, 'CONFIG', tmp_path / 'config.json')
    monkeypatch.delenv('AGENTBRIDGE_DISABLE_AUTOSTART', raising=False)
    monkeypatch.setattr(cli, 'state', lambda: info.copy())
    monkeypatch.setattr(cli, 'startup_launcher', lambda: launcher)
    monkeypatch.setattr(autostart, 'is_registered', lambda data: False)
    monkeypatch.setattr(autostart, 'register', lambda executable, data: calls.append((executable, data)))
    monkeypatch.setattr(cli, 'identity', lambda pid: 'helper')
    monkeypatch.setattr(cli.subprocess, 'Popen', lambda command, **kwargs: (
        calls.append(command) or SimpleNamespace(pid=202, poll=lambda: None)))
    monkeypatch.setattr(cli.time, 'sleep', lambda _: None)

    cli.start(SimpleNamespace(port=None, no_tray=False))

    assert [str(binary)] in calls  # No second gateway process is launched.
    assert (launcher, tmp_path) in calls
    assert json.loads(cli.STATE.read_text())['tray_pid'] == 202
    assert 'already running' in capsys.readouterr().out.lower()


def test_start_warns_when_installed_launcher_is_invalid(tmp_path, monkeypatch, capsys):
    from app import cli
    monkeypatch.setattr(cli, 'DATA', tmp_path)
    monkeypatch.setattr(cli, 'STATE', tmp_path / 'service.json')
    monkeypatch.setattr(cli, 'CONFIG', tmp_path / 'config.json')
    monkeypatch.delenv('AGENTBRIDGE_DISABLE_AUTOSTART', raising=False)
    monkeypatch.setattr(cli, 'state', lambda: None)
    monkeypatch.setattr(cli, 'startup_launcher', lambda: None)
    monkeypatch.setattr(cli, 'credentials', lambda: {'secret_key': 's', 'key_pepper': 'p', 'admin_token': 't'})
    monkeypatch.setattr(cli, 'healthy', lambda *args: True)
    monkeypatch.setattr(cli, 'identity', lambda pid: 'gateway')
    monkeypatch.setattr(cli.subprocess, 'Popen', lambda *args, **kwargs: SimpleNamespace(pid=101, poll=lambda: None))

    cli.start(SimpleNamespace(port=free_port(), no_tray=True))

    output = capsys.readouterr()
    assert 'launcher' in (output.out + output.err).lower()
    assert 'autostart' in (output.out + output.err).lower() or 'automatic startup' in (output.out + output.err).lower()


def test_macos_helper_early_exit_warns_without_stopping_gateway(tmp_path, monkeypatch, capsys):
    from app import cli
    binary = tmp_path / 'menubar' / 'LLMGatewayBar'
    binary.parent.mkdir()
    binary.touch()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    monkeypatch.setattr(cli, 'DATA', tmp_path)
    monkeypatch.setattr(cli, 'STATE', tmp_path / 'service.json')
    monkeypatch.setattr(cli, 'CONFIG', tmp_path / 'config.json')
    monkeypatch.setenv('AGENTBRIDGE_DISABLE_AUTOSTART', '1')
    monkeypatch.setattr(cli, 'state', lambda: None)
    monkeypatch.setattr(cli, 'credentials', lambda: {'secret_key': 's', 'key_pepper': 'p', 'admin_token': 't'})
    monkeypatch.setattr(cli, 'healthy', lambda *args: True)
    monkeypatch.setattr(cli, 'identity', lambda pid: 'process-identity')
    monkeypatch.setattr(cli.time, 'sleep', lambda _: None)
    processes = iter([SimpleNamespace(pid=101, poll=lambda: None), SimpleNamespace(pid=202, poll=lambda: 1)])
    monkeypatch.setattr(cli.subprocess, 'Popen', lambda *args, **kwargs: next(processes))

    cli.start(SimpleNamespace(port=free_port(), no_tray=False))

    output = capsys.readouterr()
    text = (output.out + output.err).lower().replace('status-bar', 'status bar')
    assert 'status bar' in text and ('unavailable' in text or 'failed' in text)
    assert 'status bar started' not in text
    assert json.loads(cli.STATE.read_text())['pid'] == 101
    assert 'tray_pid' not in json.loads(cli.STATE.read_text())


def test_dashboard_opens_with_fragment_and_does_not_print_token(monkeypatch, capsys):
    from app import cli
    token = 'example+token/value'
    opened = []
    from app import updates
    monkeypatch.setattr(updates, 'check_update', lambda data: {'available': False})
    monkeypatch.setattr(cli, 'state', lambda: {'port': 8766})
    monkeypatch.setattr(cli, 'credentials', lambda: {'admin_token': token})
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: opened.append(url) or True)
    monkeypatch.setattr(sys, 'argv', ['agentbridge', 'dashboard'])
    assert cli.main() == 0
    assert opened == ['http://127.0.0.1:8766/#admin_token=example%2Btoken%2Fvalue']
    assert token not in capsys.readouterr().out


def prepare_uninstall(tmp_path, monkeypatch):
    from app import cli
    root = tmp_path / 'installation'
    executable_dir = root / 'releases' / 'release.test' / 'agentbridge'
    executable_dir.mkdir(parents=True)
    executable = executable_dir / ('agentbridge.exe' if os.name == 'nt' else 'agentbridge')
    executable.touch()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    launcher = bin_dir / ('agentbridge.cmd' if os.name == 'nt' else 'agentbridge')
    if os.name == 'nt':
        launcher.write_text(f'@echo off\n"{executable}" %*\n')
    else:
        launcher.symlink_to(executable)
    data = tmp_path / 'userdata'
    data.mkdir()
    (data / 'secrets.json').write_text(json.dumps({'secret_key': 'a', 'key_pepper': 'b', 'admin_token': 'c'}))
    (data / 'database.db').touch()
    monkeypatch.setenv('AGENTBRIDGE_INSTALL_ROOT', str(root))
    monkeypatch.setenv('AGENTBRIDGE_BIN_DIR', str(bin_dir))
    monkeypatch.setattr(cli, 'FROZEN', True)
    monkeypatch.setattr(cli, 'ROOT', executable_dir)
    monkeypatch.setattr(cli, 'DATA', data)
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setattr(cli, 'stop', lambda: None)
    return cli, launcher, executable_dir.parent, data


def test_uninstall_preserves_data_and_removes_owned_release(tmp_path, monkeypatch):
    cli, launcher, release, data = prepare_uninstall(tmp_path, monkeypatch)
    unrelated = release.parent / 'other-files'
    unrelated.mkdir()
    calls = []
    if os.name == 'nt':
        monkeypatch.setattr(cli.subprocess, 'Popen', lambda *args, **kwargs: calls.append(args))
    cli.uninstall_cli()
    if os.name == 'nt':
        assert calls and launcher.exists()  # The detached helper removes it after exit.
    else:
        assert not launcher.exists() and not release.exists()
    assert (data / 'database.db').exists() and unrelated.exists()


def test_uninstall_purge_and_unverified_launcher(tmp_path, monkeypatch):
    import pytest
    cli, launcher, release, data = prepare_uninstall(tmp_path, monkeypatch)
    if os.name == 'nt':
        commands = []
        monkeypatch.setattr(cli.subprocess, 'Popen', lambda args, **kwargs: commands.append(args))
        cli.uninstall_cli(purge=True)
        import base64
        script = base64.b64decode(commands[0][-1]).decode('utf-16le')
        assert str(data) in script and 'Wait-Process' in script
    else:
        cli.uninstall_cli(purge=True)
        assert not data.exists()
    # An unrelated launcher must never be removed or cause the gateway to stop.
    if launcher.is_symlink() or launcher.exists():
        launcher.unlink()
    launcher.write_text('unrelated')
    with pytest.raises(RuntimeError, match='verify'):
        cli.uninstall_cli()
    assert launcher.read_text() == 'unrelated'


def test_uninstall_rejects_unsafe_data_directory(tmp_path, monkeypatch):
    import pytest
    cli, launcher, release, _ = prepare_uninstall(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, 'DATA', tmp_path)
    with pytest.raises(RuntimeError, match='unsafe'):
        cli.uninstall_cli(purge=True)
    assert launcher.exists() and release.exists()


def test_uninstall_source_launcher_keeps_checkout(tmp_path, monkeypatch):
    import shlex
    from app import cli
    root = tmp_path / 'checkout with spaces'
    (root / 'backend').mkdir(parents=True)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    launcher = bin_dir / ('agentbridge.cmd' if os.name == 'nt' else 'agentbridge')
    if os.name == 'nt':
        launcher.write_text(f'@echo off\nset "PYTHONPATH={root / "backend"};%PYTHONPATH%"\n"{Path(sys.executable).resolve()}" -m app.cli %*\n')
    else:
        launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(str(root / 'agentbridge')) + ' "$@"\n')
    monkeypatch.setenv('AGENTBRIDGE_BIN_DIR', str(bin_dir))
    monkeypatch.setattr(cli, 'FROZEN', False)
    monkeypatch.setattr(cli, 'ROOT', root)
    monkeypatch.setattr(cli, 'stop', lambda: None)
    cli.uninstall_cli()
    assert not launcher.exists() and root.is_dir()


def test_public_help_describes_commands_and_hides_helpers(monkeypatch, capsys):
    import pytest
    from app import cli
    monkeypatch.setattr(sys, 'argv', ['agentbridge', '--help'])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert 'agentbridge start' in output
    assert 'uninstall' in output and 'dashboard' in output
    assert '_serve' not in output and '_tray' not in output


def test_uninstall_help_explains_data_retention(monkeypatch, capsys):
    import pytest
    from app import cli
    monkeypatch.setattr(sys, 'argv', ['agentbridge', 'uninstall', '--help'])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert 'User data is kept by default' in output and '--purge' in output
