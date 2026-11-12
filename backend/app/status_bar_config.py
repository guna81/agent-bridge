import json
import os
from pathlib import Path
from pydantic import BaseModel, Field


class EnabledProviders(BaseModel):
    codex: bool = True
    claude: bool = True
    antigravity: bool = True


class StatusBarConfig(BaseModel):
    enabled_providers: EnabledProviders = Field(default_factory=EnabledProviders)
    pinned_metric: str = "antigravity_gemini_5h"
    refresh_interval_seconds: int = 3
    antigravity_ls_address: str = ""
    antigravity_csrf_token: str = ""
    codex_sqlite_path: str = ""
    claude_json_path: str = ""


def _config_file_path() -> Path:
    # Try finding data dir relative to backend
    cur = Path(__file__).resolve().parent.parent / "data" / "status_bar_config.json"
    return cur


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
