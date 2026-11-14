"""The compatibility manager must delegate without installing another daemon."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Bash compatibility manager')


def test_manager_delegates_to_installed_cli(tmp_path):
    launcher = tmp_path / 'agentbridge'
    launcher.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    launcher.chmod(0o755)
    script = Path(__file__).resolve().parents[2] / 'manage-service.sh'
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'], 'AGENTBRIDGE_LEGACY_SERVICE': '0'}
    for action, expected in [('start', ['start']), ('install', ['start', 'autostart', 'enable']), ('restart', ['stop', 'start']), ('uninstall', ['autostart', 'disable', 'stop'])]:
        result = subprocess.run([shutil.which('bash'), str(script), action], env=env, text=True, capture_output=True, check=True)
        assert result.stdout.splitlines() == expected
