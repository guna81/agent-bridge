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
        stdout = ''
        if command[1] == 'print' and loaded:
            path = tmp_path / 'Library/LaunchAgents' / f'{autostart.LABEL}.plist'
            with path.open('rb') as stream:
                generation = plistlib.load(stream)['EnvironmentVariables'][autostart.GENERATION]
            stdout = f'\tenvironment = {{\n\t\t{autostart.GENERATION} => {generation}\n\t}}\n'
        return SimpleNamespace(returncode=1 if command[1] == 'print' and not loaded else 0,
                               stdout=stdout, stderr='')
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


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
def test_macos_automatic_registration_preserves_other_data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    launcher = tmp_path / 'agentbridge'
    launcher.touch()
    path = tmp_path / 'Library/LaunchAgents' / f'{autostart.LABEL}.plist'
    path.parent.mkdir(parents=True)
    original = plistlib.dumps({'EnvironmentVariables': {'AGENTBRIDGE_HOME': '/other/data'}})
    path.write_bytes(original)
    with pytest.raises(RuntimeError, match='another data directory'):
        autostart.register(launcher, tmp_path / 'data')
    assert path.read_bytes() == original


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
def test_macos_reregistration_reloads_idle_job_with_updated_plist(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    launcher = tmp_path / 'new-launcher'
    launcher.touch()
    data = tmp_path / 'new-data'
    path = tmp_path / 'Library/LaunchAgents' / f'{autostart.LABEL}.plist'
    path.parent.mkdir(parents=True)
    with path.open('wb') as stream:
        plistlib.dump({'Label': autostart.LABEL, 'ProgramArguments': ['/old/launcher', 'start']}, stream)
    calls = []

    def launchctl(command, **kwargs):
        calls.append(command)
        if command[1] == 'bootstrap':
            with path.open('rb') as stream:
                assert plistlib.load(stream)['ProgramArguments'] == [str(launcher), 'start']
        return SimpleNamespace(returncode=0, stdout=(f'gui/501/{autostart.LABEL} = {{\n'
                                                    '\tstate = not running\n\tendpoints = {\n'
                                                    '\t\tstate = active\n\t\tstate = active\n\t}\n}\n'), stderr='')
    monkeypatch.setattr(autostart.subprocess, 'run', launchctl)

    autostart.register(launcher, data)
    domain = f'gui/{os.getuid()}'
    assert calls == [['launchctl', 'print-disabled', domain], ['launchctl', 'print', f'{domain}/{autostart.LABEL}'],
                     ['launchctl', 'bootout', f'{domain}/{autostart.LABEL}'], ['launchctl', 'bootstrap', domain, str(path)]]


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
@pytest.mark.parametrize('state', ['\tstate = running\n\tpid = 123\n', '', '\tstate = unexpected\n',
                                   '\tstate = waiting\n\tpid = 123\n', '\tstate = running\n\tstate = waiting\n'])
def test_macos_reregistration_defers_when_job_may_be_running(tmp_path, monkeypatch, state):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    launcher = tmp_path / 'launcher'
    launcher.touch()
    calls = []
    def launchctl(command, **kwargs):
        calls.append(command[1])
        return SimpleNamespace(returncode=0, stdout=state if command[1] == 'print' else '', stderr='')
    monkeypatch.setattr(autostart.subprocess, 'run', launchctl)

    with pytest.raises(RuntimeError, match='reload deferred'):
        autostart.register(launcher, tmp_path / 'data')
    assert calls == ['print-disabled', 'print']
    assert (tmp_path / 'Library/LaunchAgents' / f'{autostart.LABEL}.plist').exists()
    # The saved plist is newer than the still-loaded job, so status must not
    # mistake the stale job for the newly registered configuration.
    assert not autostart.is_registered(tmp_path / 'data')


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
@pytest.mark.parametrize('explicit', [False, True])
def test_macos_registration_preserves_disabled_choice(tmp_path, monkeypatch, explicit):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    launcher = tmp_path / 'launcher'
    launcher.touch()
    calls = []
    def launchctl(command, **kwargs):
        calls.append(command[1])
        return SimpleNamespace(returncode=1 if command[1] == 'print' else 0,
                               stdout=f'"{autostart.LABEL}" => disabled', stderr='')
    monkeypatch.setattr(autostart.subprocess, 'run', launchctl)

    if explicit:
        autostart.register(launcher, tmp_path / 'data', enable_disabled=True)
        assert calls == ['enable', 'print', 'bootstrap']
    else:
        with pytest.raises(RuntimeError, match='disabled in macOS'):
            autostart.register(launcher, tmp_path / 'data')
        assert calls == ['print-disabled']


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
@pytest.mark.parametrize(('failure', 'message'), [('bootout', 'could not be unloaded'), ('bootstrap', 'could not be loaded')])
def test_macos_reload_reports_launchctl_failures(tmp_path, monkeypatch, failure, message):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    launcher = tmp_path / 'launcher'
    launcher.touch()
    calls = []
    def launchctl(command, **kwargs):
        calls.append(command[1])
        return SimpleNamespace(returncode=int(command[1] == failure), stdout='\tstate = waiting\n', stderr='failure')
    monkeypatch.setattr(autostart.subprocess, 'run', launchctl)

    with pytest.raises(RuntimeError, match=message):
        autostart.register(launcher, tmp_path / 'data')
    if failure == 'bootout':
        assert 'bootstrap' not in calls


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


@pytest.mark.skipif(os.name == 'nt', reason='Unix LaunchAgent paths')
def test_status_reports_last_login_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(cli, 'DATA', tmp_path)
    monkeypatch.setattr(autostart, 'is_registered', lambda data: True)
    monkeypatch.setattr(autostart.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout='\tlast exit code = 126\n', stderr=''))
    cli.autostart_command('status')
    output = capsys.readouterr()
    assert 'enabled' in output.out
    assert '126' in output.err and 'autostart.log' in output.err


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
