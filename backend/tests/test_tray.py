import importlib
import importlib.util
import sys

import pytest


@pytest.fixture
def tray(monkeypatch):
    if importlib.util.find_spec('pystray') is None or importlib.util.find_spec('PIL') is None:
        pytest.skip('cross-platform tray dependencies are not installed')
    monkeypatch.setenv('PYSTRAY_BACKEND', 'dummy')
    monkeypatch.setenv('PROXY_ADMIN_TOKEN', 'test-token')
    sys.modules.pop('app.tray', None)
    return importlib.import_module('app.tray')


def test_remaining_and_icon(tray):
    assert tray.remaining({'used_percent': 30}) == 70
    assert tray.remaining({'used_percent': 120}) == 0
    assert tray.remaining(None) is None
    assert tray.detail({'used_percent': 30, 'reset_str': 'tomorrow'}) == '70% left · resets tomorrow'
    data = {'config': {'selected_clis': ['codex', 'claude']},
            'rate_limits': {'codex': {'five_hour': {'used_percent': 30}}}}
    assert tray.usage_icon(data).size == (64, 64)


def test_selection_uses_shared_config(tray, monkeypatch):
    instance = tray.Tray()
    instance.data = {'config': {'selected_clis': ['codex']}, 'rate_limits': {}}
    sent = []
    monkeypatch.setattr(tray, 'request', lambda path, body: sent.append((path, body)))
    monkeypatch.setattr(instance, 'update', lambda: None)
    instance.select('claude')
    assert sent == [('/admin/status-bar/config', {'selected_clis': ['codex', 'claude']})]
    instance.select('codex')
    assert len(sent) == 1  # At least one provider must remain selected.
    assert instance.menu() is not None


def test_compact_display_and_refresh_settings(tray):
    compact = tray.usage_icon({'config': {'display_mode': 'compact'}})
    bars = tray.usage_icon({'config': {'display_mode': 'bars', 'selected_clis': ['codex']}})
    assert compact.getpixel((0, 0))[3] == 0
    assert bars.getpixel((0, 0))[3] == 255


def test_status_bar_config_rejects_invalid_display_and_interval():
    from pydantic import ValidationError
    from app.status_bar_config import StatusBarConfig
    assert StatusBarConfig().display_mode == 'bars'
    assert StatusBarConfig(refresh_interval_seconds=2, display_mode='compact').refresh_interval_seconds == 2
    with pytest.raises(ValidationError):
        StatusBarConfig(display_mode='widget')
    for seconds in (2, 5, 10, 30):
        assert StatusBarConfig(refresh_interval_seconds=seconds).refresh_interval_seconds == seconds
    for seconds in (1, 3, 4, 300):
        with pytest.raises(ValidationError):
            StatusBarConfig(refresh_interval_seconds=seconds)


def test_indicator_defaults_on_and_config_persists(tmp_path, monkeypatch):
    from app import status_bar_config
    path = tmp_path / 'status_bar_config.json'
    monkeypatch.setattr(status_bar_config, '_config_file_path', lambda: path)
    assert status_bar_config.load_status_bar_config().indicator_enabled is True
    path.write_text('{"display_mode":"compact"}')
    assert status_bar_config.load_status_bar_config().indicator_enabled is True
    config = status_bar_config.load_status_bar_config()
    config.indicator_enabled = False
    status_bar_config.save_status_bar_config(config)
    assert status_bar_config.load_status_bar_config().indicator_enabled is False


def test_tray_visibility_changes_without_stopping_polling(tray, monkeypatch):
    from types import SimpleNamespace
    instance = tray.Tray()
    instance.icon = SimpleNamespace(icon=None, title='', menu=None, visible=True, update_menu=lambda: None)
    response = {'config': {'indicator_enabled': False}, 'rate_limits': {}}
    monkeypatch.setattr(tray, 'request', lambda path: response)
    instance.update()
    assert instance.icon.visible is False
    assert not instance.stopped.is_set()
    def offline(path):
        raise OSError('offline')
    monkeypatch.setattr(tray, 'request', offline)
    instance.update()
    assert instance.icon.visible is False
    response['config']['indicator_enabled'] = True
    monkeypatch.setattr(tray, 'request', lambda path: response)
    instance.update()
    assert instance.icon.visible is True


def test_legacy_interval_migration_preserves_other_settings(tmp_path, monkeypatch):
    from app import status_bar_config
    path = tmp_path / 'status_bar_config.json'
    monkeypatch.setattr(status_bar_config, '_config_file_path', lambda: path)
    path.write_text('{"refresh_interval_seconds": 3, "display_mode": "compact"}')
    config = status_bar_config.load_status_bar_config()
    assert config.refresh_interval_seconds == 2
    assert config.display_mode == 'compact'
