import json
import os
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class EnabledProviders(BaseModel):
    codex: bool = True
    claude: bool = True
    antigravity: bool = True


class StatusBarConfig(BaseModel):
    indicator_enabled: bool = True
    enabled_providers: EnabledProviders = Field(default_factory=EnabledProviders)
    pinned_metric: str = "antigravity_gemini_5h"
    selected_clis: list[str] = Field(default_factory=lambda: ["antigravity"], min_length=1, max_length=2)

    @model_validator(mode="before")
    @classmethod
    def migrate_selection(cls, value):
        if isinstance(value, dict) and "selected_clis" not in value:
            value = dict(value)
            pinned = value.get("pinned_metric", "antigravity_gemini_5h")
            value["selected_clis"] = [next((p for p in ("codex", "claude", "antigravity") if pinned.startswith(p)), "antigravity")]
        return value

    @model_validator(mode="after")
    def validate_selection(self):
        if len(set(self.selected_clis)) != len(self.selected_clis) or any(p not in ("codex", "claude", "antigravity") for p in self.selected_clis):
            raise ValueError("Select one or two distinct CLI providers")
        return self
    display_mode: Literal["bars", "compact"] = "bars"
    refresh_interval_seconds: Literal[2, 5, 10, 30] = 5
    antigravity_ls_address: str = ""
    antigravity_csrf_token: str = ""
    codex_sqlite_path: str = ""
    claude_json_path: str = ""


def _config_file_path() -> Path:
    from .config import get_settings
    return get_settings().data_dir / "status_bar_config.json"


def load_status_bar_config() -> StatusBarConfig:
    p = _config_file_path()
    cfg = StatusBarConfig()
    
    # Auto-seed from environment if present
    env_ls = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "")
    env_csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")
    if env_ls:
        cfg.antigravity_ls_address = env_ls
    if env_csrf:
        cfg.antigravity_csrf_token = env_csrf

    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Preserve older settings while moving legacy intervals to a supported choice.
            interval = data.get("refresh_interval_seconds")
            if isinstance(interval, (int, float)) and interval not in (2, 5, 10, 30):
                data["refresh_interval_seconds"] = min((2, 5, 10, 30), key=lambda choice: abs(choice - interval))
            cfg = StatusBarConfig.model_validate(data)
            # If config has empty LS or CSRF but env has them, use env
            if not cfg.antigravity_ls_address and env_ls:
                cfg.antigravity_ls_address = env_ls
            if not cfg.antigravity_csrf_token and env_csrf:
                cfg.antigravity_csrf_token = env_csrf
        except Exception:
            pass
            
    return cfg


def save_status_bar_config(new_cfg: StatusBarConfig) -> StatusBarConfig:
    p = _config_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(new_cfg.model_dump(), f, indent=2)
    return new_cfg
