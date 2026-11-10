"""Minimal environment for CLI subprocesses. The server's own environment is never inherited."""
from __future__ import annotations

import getpass
import os

from ..adapters.base import RunContext
from ..config import get_settings


def host_home() -> str:
    return os.path.expanduser("~")


def build_env(ctx: RunContext, extra: dict[str, str] | None = None, *, pty: bool = False) -> dict[str, str]:
    s = get_settings()
    home = host_home() if ctx.use_host_home else str(ctx.home)
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": home,
        "USER": _user(),
        "LOGNAME": _user(),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "xterm-256color" if pty else "dumb",
        "TMPDIR": str(ctx.scratch or ctx.workdir),
        "NO_COLOR": "1",
        "CI": "1",
    }
    for name in filter(None, (n.strip() for n in s.cli_env_passthrough.split(","))):
        if name in os.environ:
            env[name] = os.environ[name]
    env.update(extra or {})
    return env


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "proxy"
