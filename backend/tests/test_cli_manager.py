import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def test_cli_start_and_stop(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    # The managed service must not seed the integration suite's shared database.
    for key in ('PROXY_DATABASE_URL', 'PROXY_QUEUE_BACKEND', 'PROXY_REDIS_URL'):
        env.pop(key, None)
    env['AGENTBRIDGE_HOME'] = str(tmp_path)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    command = [sys.executable, '-m', 'app.cli']
    def run(*args):
        return subprocess.run([*command, *args], env=env, capture_output=True, text=True, timeout=20)
    try:
        started = run('start', '--personal', '--no-tray', '--port', str(port))
        assert started.returncode == 0, started.stderr
        assert 'ready' in run('status').stdout
        assert json.loads((tmp_path / 'service.json').read_text())['personal'] is True
        occupied = run('start', '--port', str(port))
        assert 'already running' in occupied.stdout
        assert run('stop').returncode == 0
        assert 'not running' in run('status').stdout
    finally:
        run('stop')


def test_dashboard_opens_with_fragment_and_does_not_print_token(monkeypatch, capsys):
    from app import cli
    token = 'example+token/value'
    opened = []
    monkeypatch.setattr(cli, 'state', lambda: {'port': 8766})
    monkeypatch.setattr(cli, 'credentials', lambda: {'admin_token': token})
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: opened.append(url) or True)
    monkeypatch.setattr(sys, 'argv', ['agentbridge', 'dashboard'])
    assert cli.main() == 0
    assert opened == ['http://127.0.0.1:8766/#admin_token=example%2Btoken%2Fvalue']
    assert token not in capsys.readouterr().out
