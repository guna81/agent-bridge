"""Insert the source version into the GitHub Pages header before deployment."""
from pathlib import Path
import re
import tomllib

root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / 'backend' / 'pyproject.toml').read_text())['project']['version']
page = root / 'docs' / 'index.html'
html = page.read_text()
html, count = re.subn(r'(<span\b[^>]*\bdata-project-version\b[^>]*>)[^<]*(</span>)',
                      lambda match: f'{match[1]}dev v{version}{match[2]}', html)
if count != 1:
    raise SystemExit('Expected exactly one project version placeholder in docs/index.html')
page.write_text(html)
