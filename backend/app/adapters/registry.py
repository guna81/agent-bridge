"""Adding a CLI = one adapter file + one entry here."""
from __future__ import annotations

from typing import Callable

from .agy import AgyAdapter
from .base import CliAdapter
from .claude import DEFAULT_RAW_PROMPT, ClaudeAdapter
from .codex import CodexAdapter
from .custom import CustomAdapter
from .gemini import GeminiAdapter

ADAPTERS: dict[str, Callable[[], CliAdapter]] = {
    "claude": ClaudeAdapter,
    "agy": AgyAdapter,
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
    "custom": CustomAdapter,
}

# Defaults used when seeding the provider table.
BUILTIN_PROVIDERS = {
    "claude": {
        "binary_path": "claude",
        "default_model": "sonnet",
        "models": ["sonnet", "opus", "haiku"],
    },
    "agy": {
        "binary_path": "agy",
        "default_model": "gemini-3.8-flash-medium",
        "models": [
            "gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low",
            "claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium",
        ],
    },
    # "default" = no --model flag: the CLI uses the model its own config selects. Add real model ids in the UI.
    "codex": {"binary_path": "codex", "default_model": "default", "models": ["default"]},
    "gemini": {"binary_path": "gemini", "default_model": "default", "models": ["default", "auto", "pro", "flash", "flash-lite"]},
}  # fmt: skip


def new_adapter(kind: str) -> CliAdapter:
    try:
        return ADAPTERS[kind]()
    except KeyError:
        raise ValueError(f"unknown adapter kind {kind!r}") from None


__all__ = ["ADAPTERS", "BUILTIN_PROVIDERS", "DEFAULT_RAW_PROMPT", "new_adapter"]
