"""Minimal Prometheus text-format metrics. No client library: a handful of counters is all we need.

Counters are per-process; with several instances, scrape each one (Prometheus sums them).
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))

_HELP = {
    "proxy_requests_total": "Chat requests by provider, model and final status (ok|error|aborted).",
    "proxy_tokens_total": "Tokens by provider, model and direction (input|output).",
    "proxy_cost_usd_total": "Cost in USD by provider and model (CLI-reported or estimated).",
    "proxy_request_duration_seconds_sum": "Total wall time spent in chat requests.",
    "proxy_request_duration_seconds_count": "Number of chat requests timed.",
    "proxy_http_rejections_total": "Requests rejected before running, by reason.",
}


def inc(name: str, value: float = 1.0, **labels: str) -> None:
    with _lock:
        _counters[name][tuple(sorted(labels.items()))] += value


def observe_request(provider: str, model: str, status: str, in_tok: int, out_tok: int, cost: float, seconds: float) -> None:
    lb = {"provider": provider, "model": model}
    inc("proxy_requests_total", status=status, **lb)
    inc("proxy_tokens_total", in_tok, direction="input", **lb)
    inc("proxy_tokens_total", out_tok, direction="output", **lb)
    inc("proxy_cost_usd_total", cost, **lb)
    inc("proxy_request_duration_seconds_sum", seconds, **lb)
    inc("proxy_request_duration_seconds_count", 1, **lb)


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(gauges: dict[str, float] | None = None) -> str:
    lines: list[str] = []
    with _lock:
        snap = {n: dict(v) for n, v in _counters.items()}
    for name in sorted(snap):
        lines.append(f"# HELP {name} {_HELP.get(name, name)}")
        lines.append(f"# TYPE {name} counter")
        for labels, val in sorted(snap[name].items()):
            lb = ",".join(f'{k}="{_esc(v)}"' for k, v in labels)
            lines.append(f"{name}{{{lb}}} {val:g}" if lb else f"{name} {val:g}")
    for name, val in sorted((gauges or {}).items()):
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {val:g}")
    return "\n".join(lines) + "\n"


def reset() -> None:  # tests
    with _lock:
        _counters.clear()
