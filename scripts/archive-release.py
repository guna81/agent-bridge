"""Archive the local release package and write its SHA-256 checksum."""
import hashlib
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
platform = sys.argv[1]
if platform not in {'macos-arm64', 'linux-x86_64', 'windows-x86_64'}:
    raise SystemExit('Unsupported release platform')
release = root / 'build' / 'release'
artifacts = root / 'build' / 'artifacts'
artifacts.mkdir(parents=True, exist_ok=True)
name = artifacts / f'agentbridge-{platform}'
archive = Path(shutil.make_archive(str(name), 'zip' if platform.startswith('windows') else 'gztar', root_dir=release, base_dir='agentbridge'))
digest = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
archive.with_name(archive.name + '.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
print(archive)
