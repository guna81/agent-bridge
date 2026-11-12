"""Rough cost estimates, used ONLY when a CLI doesn't report cost (agy reports tokens, not dollars).

Numbers are USD per million tokens (input, output) and are indicative; override with PROXY_* settings
or edit here. Claude's own `total_cost_usd` is always preferred over this table.
"""
from __future__ import annotations

import math

# (substring match on model slug, input $/Mtok, output $/Mtok) - first match wins
PRICE_TABLE: list[tuple[str, float, float]] = [
    ("opus", 15.0, 75.0),
    ("sonnet", 3.0, 15.0),
    ("haiku", 1.0, 5.0),
    ("flash-lite", 0.10, 0.40),
    ("flash", 0.30, 2.50),
    ("gpt-oss", 0.15, 0.60),
    ("gemini", 1.25, 10.0),
    ("pro", 1.25, 10.0),
    ("mini", 0.25, 2.0),
    ("gpt", 1.25, 10.0),
    ("codex", 1.25, 10.0),
]
DEFAULT_PRICE = (1.0, 5.0)


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4)) if text else 0


def pricing_rate(model: str, rates: dict | None = None) -> tuple[float, float]:
    m = model.lower()
    override = (rates or {}).get(model)
    try:
        pin, pout = (float(override[0]), float(override[1])) if isinstance(override, (list, tuple)) and len(override) == 2 else (-1.0, -1.0)
    except (TypeError, ValueError):
        pin, pout = -1.0, -1.0
    if not math.isfinite(pin) or not math.isfinite(pout) or pin < 0 or pout < 0:
        pin, pout = next(((i, o) for key, i, o in PRICE_TABLE if key in m), DEFAULT_PRICE)
    return pin, pout


def estimate_cost(model: str, input_tokens: int, output_tokens: int, rates: dict | None = None) -> float:
    pin, pout = pricing_rate(model, rates)
    return (input_tokens * pin + output_tokens * pout) / 1_000_000
