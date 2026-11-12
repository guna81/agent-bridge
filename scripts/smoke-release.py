"""Exercise the packaged gateway using isolated temporary user data."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import urllib.request

root = Path(__file__).resolve().parents[1]
exe = root / 'build' / 'release' / 'agentbridge' / ('agentbridge.exe' if os.name == 'nt' else 'agentbridge')
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
with tempfile.TemporaryDirectory() as home:
    env = os.environ.copy()
    env['AGENTBRIDGE_HOME'] = home
    def run(*args):
        result = subprocess.run([str(exe), *args], capture_output=True, text=True, env=env, timeout=45)
        if result.returncode:
            raise RuntimeError(f'{args} failed: {result.stdout}\n{result.stderr}')
        return result.stdout
    try:
        print(run('start', '--no-tray', '--port', str(port)))
        assert 'ready' in run('status')
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=5) as response:
            assert response.status == 200 and b'<html' in response.read().lower()
        print(run('stop'))
    finally:
        subprocess.run([str(exe), 'stop'], env=env, capture_output=True, timeout=45)
print('Packaged gateway and dashboard passed smoke test.')
