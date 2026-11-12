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
    with pytest.raises(ValidationError):
        StatusBarConfig(refresh_interval_seconds=1)
