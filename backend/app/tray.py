"""Cross-platform tray client for the local AgentBridge gateway."""
from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
import webbrowser

from PIL import Image, ImageDraw
import pystray

NAMES = {"codex": "Codex", "claude": "Claude Code", "antigravity": "Antigravity"}
BASE = f"http://127.0.0.1:{int(os.environ.get('PROXY_PORT', '43187'))}"
TOKEN = os.environ['PROXY_ADMIN_TOKEN']


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)


def remaining(window):
    if not isinstance(window, dict) or window.get('used_percent') is None:
        return None
    return max(0, min(100, 100 - float(window['used_percent'])))


def usage_icon(data):
    """Two bars per selected provider; text details remain readable in the menu."""
    if data.get("config", {}).get("display_mode", "bars") == "compact":
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        # Match the app mark on a dark rounded tile so it remains visible on
        # both light and dark system trays.
        draw.rounded_rectangle((1, 1, 62, 62), radius=18, fill=(16, 17, 20, 255))
        white = (247, 248, 250, 255)
        blue = (101, 151, 255, 255)
        points = [(12, 40), (21, 40), (29, 25), (30, 24), (32, 23),
                  (34, 24), (35, 25), (43, 40), (52, 40)]
        draw.line(points, fill=white, width=5, joint="curve")
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=white)
        draw.line((26, 40, 38, 40), fill=blue, width=5)
        for x in (26, 38):
            draw.ellipse((x - 2, 38, x + 2, 42), fill=blue)
        return image
    image = Image.new('RGBA', (64, 64), (20, 29, 43, 255))
    draw = ImageDraw.Draw(image)
    selected = data.get('config', {}).get('selected_clis', ['antigravity'])[:2]
    limits = data.get('rate_limits') or {}
    height = 64 // max(1, len(selected))
    for index, name in enumerate(selected):
        top = index * height
        draw.text((3, top + 2), {'codex': 'O', 'claude': 'C', 'antigravity': 'G'}.get(name, '?'), fill='white')
        for row, key in enumerate(('five_hour', 'weekly')):
            y = top + 6 + row * 10
            draw.rounded_rectangle((16, y, 61, y + 6), 2, fill=(70, 78, 90))
            value = remaining((limits.get(name) or {}).get(key))
            if value is not None and value > 0:
                color = (53, 201, 139) if value > 30 else (242, 180, 63) if value > 10 else (238, 91, 91)
                draw.rounded_rectangle((16, y, 16 + int(45 * value / 100), y + 6), 2, fill=color)
    return image


def detail(window):
    value = remaining(window)
    if value is None:
        return 'Unavailable'
    reset = window.get('reset_str')
    return f'{value:.0f}% left' + (f' · resets {reset}' if reset else '')


class Tray:
    def __init__(self):
        self.data = {}
        self.stopped = threading.Event()
        self.refresh_event = threading.Event()
        self.indicator_enabled = True
        self.icon = pystray.Icon('AgentBridge', usage_icon({}), 'AgentBridge')

    def update(self):
        try:
            self.data = request('/admin/status-bar')
            self.indicator_enabled = self.data.get('config', {}).get('indicator_enabled', True)
            self.icon.icon = usage_icon(self.data)
            self.icon.title = 'AgentBridge: remaining usage (top: 5h, bottom: weekly)'
        except Exception:
            self.data = {}
            self.icon.title = 'AgentBridge: gateway unavailable'
        self.icon.menu = self.menu()
        self.icon.update_menu()
        self.icon.visible = self.indicator_enabled

    def select(self, name):
        selected = list(self.data.get('config', {}).get('selected_clis', ['antigravity']))
        if name in selected and len(selected) > 1:
            selected.remove(name)
        elif name not in selected and len(selected) < 2:
            selected.append(name)
        else:
            return
        try:
            request('/admin/status-bar/config', {'selected_clis': selected})
        finally:
            self.update()

    def select_interval(self, seconds):
        try:
            request('/admin/status-bar/config', {'refresh_interval_seconds': seconds})
        finally:
            self.refresh_event.set()

    def menu(self):
        selected = self.data.get('config', {}).get('selected_clis', ['antigravity'])
        limits = self.data.get('rate_limits') or {}
        items = []
        if not self.data:
            items.append(pystray.MenuItem('Gateway unavailable', None, enabled=False))
        for name, label in NAMES.items():
            windows = limits.get(name) or {}
            items += [pystray.MenuItem(label, None, enabled=False),
                      pystray.MenuItem('  5-hour: ' + detail(windows.get('five_hour')), None, enabled=False),
                      pystray.MenuItem('  Weekly: ' + detail(windows.get('weekly')), None, enabled=False)]
        def action(name):
            return lambda icon, item: self.select(name)

        choices = [pystray.MenuItem(label, action(name),
                    checked=lambda item, n=name: n in self.data.get('config', {}).get('selected_clis', ['antigravity']),
                    enabled=(name in selected and len(selected) > 1) or (name not in selected and len(selected) < 2))
                   for name, label in NAMES.items()]
        def interval_action(seconds):
            return lambda icon, item: self.select_interval(seconds)

        interval_choices = [pystray.MenuItem(f'{seconds} seconds',
                            interval_action(seconds),
                            checked=lambda item, value=seconds: self.data.get('config', {}).get('refresh_interval_seconds', 5) == value,
                            enabled=bool(self.data)) for seconds in (2, 5, 10, 30)]
        items.extend([pystray.Menu.SEPARATOR, pystray.MenuItem('Providers in tray (up to 2)', pystray.Menu(*choices)),
                      pystray.MenuItem('Refresh interval', pystray.Menu(*interval_choices)),
                      pystray.MenuItem('Open dashboard', lambda: webbrowser.open(BASE + '/#admin_token=' + urllib.parse.quote(TOKEN, safe=''))),
                      pystray.MenuItem('Refresh', lambda: self.update()),
                      pystray.MenuItem('Quit tray', self.quit)])
        return pystray.Menu(*items)

    def quit(self):
        self.stopped.set()
        self.refresh_event.set()
        self.icon.stop()

    def poll(self):
        while not self.stopped.is_set():
            self.update()
            interval = self.data.get('config', {}).get('refresh_interval_seconds', 5)
            self.refresh_event.wait(max(2, min(300, int(interval))))
            self.refresh_event.clear()

    def run(self):
        # pystray invokes setup on a worker only after the native event loop is ready.
        # Keep polling while hidden so the dashboard can turn the icon back on.
        self.icon.run(setup=lambda icon: self.poll())


if __name__ == '__main__':
    Tray().run()
