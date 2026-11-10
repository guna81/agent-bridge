from __future__ import annotations

import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import get_settings

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@contextmanager
def fresh_workdir() -> Iterator[Path]:
    """Empty temp dir per request; removed afterwards."""
    base = get_settings().data_dir / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    os.chmod(d, 0o700)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def user_home(provider: str, user_id: int | str) -> Path:
    """Persistent isolated HOME for one (provider, user) — holds that user's CLI login."""
    d = get_settings().data_dir / "homes" / _SAFE.sub("_", provider) / _SAFE.sub("_", str(user_id))
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d
