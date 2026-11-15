"""Configured and discovered provider models, shared by routing and listings."""
from __future__ import annotations

from .models import Provider


def provider_models(provider: Provider) -> list[str]:
    discovered = (provider.extra or {}).get("discovered_models", []) if provider.kind == "codex" else []
    if not isinstance(discovered, list):
        discovered = []
    return list(dict.fromkeys(
        model for model in [*(provider.models or []), *discovered, provider.default_model]
        if isinstance(model, str) and model
    ))
