import json
import os
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace

import pytest

from app import autostart, cli


@pytest.mark.skipif(os.name == 'nt', reason='Unix desktop path and quoting')
def test_linux_autostart_entry_and_owned_removal(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    launcher = tmp_path / 'bin with spaces' / 'agentbridge'
    launcher.parent.mkdir()
    launcher.touch()
    data = tmp_path / 'agentbridge data'
    autostart.register(launcher, data)
    path = tmp_path / 'config/autostart/agentbridge.desktop'
    content = path.read_text()
    assert f'"{launcher}" "start"' in content
    assert f'"AGENTBRIDGE_HOME={data}"' in content
    assert autostart.is_registered(data)
    autostart.unregister(tmp_path / 'different')
    assert path.exists()
    autostart.unregister(data)
    assert not path.exists()


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
def test_macos_launch_agent_starts_installed_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    launcher = tmp_path / 'bin/agentbridge'
    launcher.parent.mkdir()
    launcher.touch()
    data = tmp_path / 'app data'
    calls = []
    loaded = False
    def launchctl(command, **kwargs):
        nonlocal loaded
        calls.append(command)
        if command[1] == 'bootstrap':
            loaded = True
        return SimpleNamespace(returncode=1 if command[1] == 'print' and not loaded else 0,
                               stdout='', stderr='')
    monkeypatch.setattr(autostart.subprocess, 'run', launchctl)
    autostart.register(launcher, data)
    path = tmp_path / 'Library/LaunchAgents/com.agentbridge.autostart.plist'
    with path.open('rb') as f:
        plist = plistlib.load(f)
    assert plist['ProgramArguments'] == [str(launcher), 'start']
    assert plist['RunAtLoad'] and plist['EnvironmentVariables']['AGENTBRIDGE_HOME'] == str(data)
    assert any(c[1] == 'bootstrap' for c in calls)
    assert autostart.is_registered(data)
    autostart.unregister(data)
    assert not path.exists()
    assert any(c[1] == 'bootout' for c in calls)


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
@pytest.mark.parametrize(('loaded', 'disabled', 'expected'), [
    (True, False, True),
    (False, False, False),
    (True, True, False),
])
def test_macos_registration_requires_loaded_and_enabled_job(tmp_path, monkeypatch, loaded, disabled, expected):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    data = tmp_path / 'app data'
    path = tmp_path / 'Library/LaunchAgents' / f'{autostart.LABEL}.plist'
    path.parent.mkdir(parents=True)
    launcher = tmp_path / 'agentbridge'
    launcher.touch()
    with path.open('wb') as stream:
        plistlib.dump({'Label': autostart.LABEL, 'ProgramArguments': [str(launcher), 'start'],
                       'RunAtLoad': True, 'EnvironmentVariables': {'AGENTBRIDGE_HOME': str(data)}}, stream)

    def launchctl(command, **kwargs):
        if command[1] == 'print':
            return SimpleNamespace(returncode=0 if loaded else 1, stdout='', stderr='')
        if command[1] == 'print-disabled':
            value = 'disabled' if disabled else 'enabled'
            return SimpleNamespace(returncode=0, stdout=f'{{\n "{autostart.LABEL}" => {value}\n}}', stderr='')
        raise AssertionError(f'unexpected launchctl command: {command}')
    monkeypatch.setattr(autostart.subprocess, 'run', launchctl)

    assert autostart.is_registered(data) is expected


def test_autostart_enable_and_disable_preserves_other_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'DATA', tmp_path)
    monkeypatch.setattr(cli, 'CONFIG', tmp_path / 'config.json')
    cli.write_config({'personal': True, 'port': 43210})
    monkeypatch.setattr(cli, 'startup_launcher', lambda: tmp_path / 'launcher')
    calls = []
    monkeypatch.setattr(autostart, 'register', lambda launcher, data, **kwargs: calls.append(('register', launcher, data)))
    monkeypatch.setattr(autostart, 'unregister', lambda data: calls.append(('unregister', data)))
    cli.autostart_command('enable')
    assert json.loads(cli.CONFIG.read_text()) == {'personal': True, 'port': 43210, 'autostart': True}
    cli.autostart_command('disable')
    assert json.loads(cli.CONFIG.read_text()) == {'personal': True, 'port': 43210, 'autostart': False}
    assert [call[0] for call in calls] == ['register', 'unregister']


def test_windows_user_login_entry(tmp_path, monkeypatch):
    import types
    monkeypatch.setattr(sys, 'platform', 'win32')
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    values = {}
    registry = types.SimpleNamespace(HKEY_CURRENT_USER=1, REG_SZ=1, KEY_SET_VALUE=2,
        CreateKey=lambda *args: Key(), OpenKey=lambda *args: Key(),
        SetValueEx=lambda key, name, _, kind, value: values.update({name: value}),
        QueryValueEx=lambda key, name: (values[name], 1),
        DeleteValue=lambda key, name: values.pop(name))
    monkeypatch.setitem(sys.modules, 'winreg', registry)
    launcher = tmp_path / 'AgentBridge' / 'agentbridge.cmd'
    launcher.parent.mkdir()
    launcher.touch()
    data = tmp_path / 'app data'
    autostart.register(launcher, data)
    script = data / 'autostart.cmd'
    assert f'call "{launcher}" start' in script.read_text()
    assert str(script) in values['AgentBridge']
    assert autostart.is_registered(data)
    autostart.unregister(data)
    assert not script.exists() and 'AgentBridge' not in values
