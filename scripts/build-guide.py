"""Render docs-src/*.md into static HTML pages in docs/guide/ (committed; no CI build needed).

Usage: pip install markdown pymdown-extensions && python3 scripts/build-guide.py
"""
from pathlib import Path
import html
import re

import markdown

root = Path(__file__).resolve().parents[1]
src = root / "docs-src"
out = root / "docs" / "guide"

NAV = [
    ("Getting started", [("install", "Install"), ("quickstart", "Quick start"), ("cli", "Command line")]),
    ("Using the app", [("dashboard", "Dashboard"), ("subscription-usage", "Subscription usage"),
                       ("status-indicator", "Status indicator"), ("skills-and-instructions", "Skills and instructions"),
                       ("providers", "Providers"), ("models", "Models")]),
    ("API and gateway", [("api", "API reference"), ("keys-and-users", "Keys, users and budgets"),
                         ("raw-vs-agent-mode", "Raw vs agent mode")]),
    ("Reference and operations", [("configuration", "Configuration"), ("security", "Security"),
                                  ("deployment", "Deployment"), ("troubleshooting", "Troubleshooting"),
                                  ("releases", "Releases")]),
]
TITLES = {slug: title for _, items in NAV for slug, title in items}
TITLES["index"] = "Overview"

CSS = """
:root{color-scheme:dark;--bg:#0c0d10;--surface:#15171c;--surface2:#1a1d24;--text:#f5f6f8;--muted:#a9afba;--accent:#8aafff;--line:#30343d}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent)}
.top{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 24px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5}
.brand{display:flex;gap:10px;align-items:center;font-weight:750;letter-spacing:-.03em;text-decoration:none;color:var(--text)}
.brand img{width:30px;height:30px}.top nav a{color:var(--muted);text-decoration:none;font-size:.88rem;margin-left:20px}.top nav a:hover{color:var(--text)}
.layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:48px;max-width:1160px;margin:auto;padding:0 24px}
.side{position:sticky;top:67px;align-self:start;max-height:calc(100vh - 67px);overflow:auto;padding:28px 0}
.side h4{margin:22px 0 6px;font-size:.72rem;text-transform:uppercase;letter-spacing:.12em;color:var(--muted)}
.side h4:first-child{margin-top:0}
.side a{display:block;padding:5px 10px;border-radius:7px;color:var(--muted);text-decoration:none;font-size:.9rem}
.side a:hover{color:var(--text);background:var(--surface)}.side a.on{color:var(--accent);background:var(--surface2)}
main{padding:36px 0 80px;min-width:0;max-width:820px}
main img{max-width:100%;height:auto;border-radius:10px;border:1px solid var(--line);margin:18px 0;box-shadow:0 12px 32px #00000040}
h1{font-size:2.4rem;letter-spacing:-.05em;line-height:1.15;margin:0 0 20px}
h2{font-size:1.5rem;letter-spacing:-.03em;margin:44px 0 12px;padding-top:6px}
h3{font-size:1.15rem;margin:30px 0 8px}
p,li{color:#d6dae2}li{margin:4px 0}
code{font:.85em ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--surface2);border:1px solid var(--line);border-radius:5px;padding:1px 5px;color:#d0ddf4}
pre{background:#0b0d12;border:1px solid #303744;border-radius:10px;padding:16px;overflow:auto;position:relative}
pre code{background:none;border:0;padding:0;font-size:.82rem;line-height:1.65}
.copy{position:absolute;top:8px;right:8px;background:#2a3446;border:0;color:#e6ebf4;border-radius:6px;padding:4px 9px;cursor:pointer;font-size:.72rem}
.copy:hover{background:#3a4a63}
table{border-collapse:collapse;width:100%;font-size:.9rem;display:block;overflow-x:auto;margin:16px 0}
th,td{border:1px solid var(--line);padding:8px 12px;text-align:left;vertical-align:top}th{background:var(--surface)}
.admonition{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;background:var(--surface);padding:2px 16px;margin:20px 0}
.admonition.warning{border-left-color:#e0a84a}.admonition.danger{border-left-color:#e06b6b}.admonition.tip{border-left-color:#5fc59a}
.admonition-title{font-weight:700;margin:10px 0 0!important}
details{border:1px solid var(--line);border-radius:8px;background:var(--surface);padding:0 16px;margin:10px 0}
summary{cursor:pointer;padding:12px 0;font-weight:600}
.tabbed-set{margin:18px 0;border:1px solid var(--line);border-radius:10px;background:var(--surface);overflow:hidden}
.tabbed-set>input{position:absolute;opacity:0;pointer-events:none}
.tabbed-labels{display:flex;flex-wrap:wrap;border-bottom:1px solid var(--line)}
.tabbed-labels>label{padding:10px 16px;cursor:pointer;color:var(--muted);font-size:.88rem;font-weight:600;border-bottom:2px solid transparent}
.tabbed-content>.tabbed-block{display:none;padding:0 16px 8px}
.tabbed-block pre{margin:12px 0}
.pager{display:flex;justify-content:space-between;gap:16px;margin-top:56px;padding-top:20px;border-top:1px solid var(--line);font-size:.9rem}
footer{border-top:1px solid var(--line);padding:24px;text-align:center;color:var(--muted);font-size:.82rem}
@media(max-width:820px){.layout{grid-template-columns:1fr;gap:0}.side{position:static;max-height:none;padding:16px 0;border-bottom:1px solid var(--line)}h1{font-size:1.9rem}.top nav a:not(:last-child){display:none}}
"""

TAB_CSS = "".join(
    f".tabbed-set>input:nth-child({i}):checked~.tabbed-labels>label:nth-child({i}){{color:var(--accent);border-bottom-color:var(--accent)}}"
    f".tabbed-set>input:nth-child({i}):checked~.tabbed-content>.tabbed-block:nth-child({i}){{display:block}}"
    for i in range(1, 7)
)


def render(slug: str, body_html: str, prev, nxt) -> str:
    side = []
    for group, items in NAV:
        side.append(f"<h4>{group}</h4>")
        for s, t in items:
            side.append(f'<a href="{s}.html"{" class=on" if s == slug else ""}>{t}</a>')
    side_html = f'<a href="index.html"{" class=on" if slug == "index" else ""}>Overview</a>' + "".join(side)
    pager = '<div class="pager"><span>' + (f'← <a href="{prev}.html">{TITLES[prev]}</a>' if prev else "") + \
            '</span><span>' + (f'<a href="{nxt}.html">{TITLES[nxt]}</a> →' if nxt else "") + "</span></div>"
    title = "AgentBridge Documentation" if slug == "index" else f"{TITLES[slug]} · AgentBridge Docs"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><link rel="icon" href="../assets/agentbridge-icon.svg">
<style>{CSS}{TAB_CSS}</style></head><body>
<header class="top"><a class="brand" href="../"><img src="../assets/agentbridge-icon.svg" alt="">AgentBridge</a>
<nav><a href="index.html">Docs</a><a href="https://github.com/guna81/agent-bridge/releases/latest">Releases</a><a href="https://github.com/guna81/agent-bridge">GitHub</a></nav></header>
<div class="layout"><aside class="side" aria-label="Documentation">{side_html}</aside>
<main>{body_html}{pager}</main></div>
<footer>AgentBridge is open source under the MIT license.</footer>
<script>document.querySelectorAll('pre').forEach(function(p){{var b=document.createElement('button');b.className='copy';b.textContent='Copy';b.onclick=function(){{navigator.clipboard.writeText(p.innerText.replace(/Copy$/,'').trimEnd()).then(function(){{b.textContent='Copied';setTimeout(function(){{b.textContent='Copy'}},1500)}})}};p.appendChild(b)}})</script>
</body></html>
"""


def main() -> None:
    out.mkdir(parents=True, exist_ok=True)
    order = ["index"] + [s for _, items in NAV for s, _ in items]
    md = markdown.Markdown(extensions=["admonition", "tables", "attr_list", "toc", "fenced_code",
                                       "pymdownx.superfences", "pymdownx.tabbed", "pymdownx.details"],
                           extension_configs={"pymdownx.tabbed": {"alternate_style": True}})
    for i, slug in enumerate(order):
        md.reset()
        body = md.convert((src / f"{slug}.md").read_text())
        body = re.sub(r'href="([\w-]+)\.md(#[^"]*)?"', lambda m: f'href="{m[1]}.html{m[2] or ""}"', body)
        prev = order[i - 1] if i else None
        nxt = order[i + 1] if i + 1 < len(order) else None
        (out / f"{slug}.html").write_text(render(slug, body, prev, nxt))
    print(f"wrote {len(order)} pages to {out}")


if __name__ == "__main__":
    main()
