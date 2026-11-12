"""Stamp a release tag into the build checkout without changing the repository."""
from pathlib import Path
import re
import sys


def stamp(root: Path, tag: str):
    if not re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', tag):
        raise ValueError('Release tag must be a stable version such as v0.3.0')
    version = tag[1:]
    for path, pattern in [
        (root / 'backend/pyproject.toml', r'(?m)^(version\s*=\s*")[^"]+("\s*)$'),
        (root / 'backend/app/updates.py', r'(?m)^(VERSION\s*=\s*")[^"]+("[^\n]*)$'),
    ]:
        content, count = re.subn(pattern, lambda match: match[1] + version + match[2], path.read_text())
        if count != 1:
            raise ValueError(f'Expected one version declaration in {path}')
        path.write_text(content)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: set-release-version.py vX.Y.Z')
    try:
        stamp(Path(__file__).resolve().parents[1], sys.argv[1])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
