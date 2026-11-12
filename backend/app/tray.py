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
        color = (38, 215, 218, 255)
        draw.line([(5, 39), (13, 37), (20, 29), (26, 23), (32, 21),
                   (38, 23), (44, 29), (51, 37), (59, 39)], fill=color, width=5, joint="curve")
        draw.line((8, 46, 56, 46), fill=color, width=5)
        draw.line((21, 32, 21, 46), fill=color, width=4)
        draw.line((43, 32, 43, 46), fill=color, width=4)
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
        self.icon = pystray.Icon('AgentBridge', usage_icon({}), 'AgentBridge')

    def update(self):
        try:
            self.data = request('/admin/status-bar')
            self.icon.icon = usage_icon(self.data)
            self.icon.title = 'AgentBridge: remaining usage (top: 5h, bottom: weekly)'
        except Exception:
            self.data = {}
            self.icon.title = 'AgentBridge: gateway unavailable'
        self.icon.menu = self.menu()
        self.icon.update_menu()

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
        items.extend([pystray.Menu.SEPARATOR, pystray.MenuItem('Providers in tray (up to 2)', pystray.Menu(*choices)),
                      pystray.MenuItem('Open dashboard', lambda: webbrowser.open(BASE + '/#admin_token=' + urllib.parse.quote(TOKEN, safe=''))),
                      pystray.MenuItem('Refresh', lambda: self.update()),
                      pystray.MenuItem('Quit tray', self.quit)])
        return pystray.Menu(*items)

    def quit(self):
        self.stopped.set()
        self.icon.stop()

    def poll(self):
        while not self.stopped.is_set():
            self.update()
            interval = self.data.get('config', {}).get('refresh_interval_seconds', 3)
            self.stopped.wait(max(2, min(300, int(interval))))

    def run(self):
        threading.Thread(target=self.poll, daemon=True).start()
        self.icon.run()


if __name__ == '__main__':
    Tray().run()
