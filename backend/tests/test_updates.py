import json
import sys
import time
import tomllib
from pathlib import Path

from app import updates


def test_version_matches_package_metadata():
    project = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())
    assert updates.VERSION == project['project']['version']


def test_update_check_caches_stable_releases(tmp_path, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps({'tag_name': 'v99.0.0'}).encode()
    calls = []
    monkeypatch.setattr(updates.urllib.request, 'urlopen', lambda *args, **kwargs: calls.append(args) or Response())
    first = updates.check_update(tmp_path)
    second = updates.check_update(tmp_path)
    assert first['available'] and first['latest'] == '99.0.0'
    assert second == first and len(calls) == 1


def test_update_check_handles_offline_and_invalid_release(tmp_path, monkeypatch):
    def offline(*args, **kwargs): raise OSError('offline')
    monkeypatch.setattr(updates.urllib.request, 'urlopen', offline)
    assert not updates.check_update(tmp_path)['available']
    (tmp_path / 'update-check.json').write_text(json.dumps({'checked_at': time.time(), 'latest': 'v99.0.0-rc1'}))
    assert not updates.check_update(tmp_path)['available']


def test_cli_prints_update_notice(monkeypatch, capsys):
    from app import cli
    monkeypatch.setattr(updates, 'check_update', lambda _: {'available': True, 'current': '0.2.0', 'latest': '0.3.0', 'release_url': updates.RELEASES_URL})
    monkeypatch.setattr(cli, 'state', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['agentbridge', 'status'])
    assert cli.main() == 0
    assert '0.3.0' in capsys.readouterr().err


def test_update_source_checkout_is_not_overwritten(monkeypatch, capsys):
    from app import cli
    monkeypatch.setattr(cli, 'FROZEN', False)
    monkeypatch.setattr(sys, 'argv', ['agentbridge', 'update'])
    assert cli.main() == 1
    assert 'source checkout' in capsys.readouterr().err


def test_update_installed_release_runs_bundled_installer(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from app import cli
    if sys.platform == 'win32':
        import pytest
        pytest.skip('Unix launcher test')
    root = tmp_path / 'releases' / 'release-a' / 'agentbridge'
    root.mkdir(parents=True)
    executable = root / 'agentbridge'
    executable.touch()
    installer = root / 'installer' / 'install.sh'
    installer.parent.mkdir()
    installer.touch()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'agentbridge').symlink_to(executable)
    monkeypatch.setenv('AGENTBRIDGE_INSTALL_ROOT', str(tmp_path))
    monkeypatch.setenv('AGENTBRIDGE_BIN_DIR', str(bin_dir))
    monkeypatch.setattr(cli, 'FROZEN', True)
    monkeypatch.setattr(cli, 'ROOT', root)
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setattr(updates, 'check_update', lambda _, force=False: {'latest': '0.3.0', 'current': '0.2.0', 'available': True})
    called = []
    monkeypatch.setattr(cli.subprocess, 'run', lambda command, **kwargs: called.append(command) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli, 'state', lambda: {'pid': 1})
    cli.update_cli()
    assert called == [['sh', str(installer)]]
    assert 'agentbridge stop' in capsys.readouterr().out


def test_update_does_not_run_installer_when_current(monkeypatch, capsys):
    from app import cli
    monkeypatch.setattr(cli, 'FROZEN', True)
    monkeypatch.setattr(updates, 'check_update', lambda _, force=False: {'latest': '0.2.0', 'current': '0.2.0', 'available': False})
    cli.update_cli()
    assert 'already up to date' in capsys.readouterr().out


def test_release_tag_stamps_build_version_without_changing_checkout(tmp_path):
    import importlib.util
    import shutil
    import pytest
    source = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('release_version', source / 'scripts/set-release-version.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'backend/app').mkdir(parents=True)
    shutil.copy(source / 'backend/pyproject.toml', tmp_path / 'backend/pyproject.toml')
    shutil.copy(source / 'backend/app/updates.py', tmp_path / 'backend/app/updates.py')
    module.stamp(tmp_path, 'v1.2.3')
    assert tomllib.loads((tmp_path / 'backend/pyproject.toml').read_text())['project']['version'] == '1.2.3'
    assert 'VERSION = "1.2.3"' in (tmp_path / 'backend/app/updates.py').read_text()
    with pytest.raises(ValueError):
        module.stamp(tmp_path, 'v1.2.3-rc1')
