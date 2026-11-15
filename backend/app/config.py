from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROXY_", env_file=".env", extra="ignore")

    # storage
    data_dir: Path = Path("./data")
    database_url: str = ""  # default: sqlite in data_dir

    # secrets (Fernet key = urlsafe base64 32 bytes; generate with `python -m app.security`)
    secret_key: str = ""
    key_pepper: str = "change-me"
    admin_token: str = ""  # required for /admin and the UI

    # network
    host: str = "127.0.0.1"
    port: int = 8000

    # concurrency / limits
    max_concurrency: int = 4
    per_user_concurrency: int = 2
    queue_timeout_s: float = 30.0
    request_timeout_s: float = 300.0
    max_body_bytes: int = 10 * 1024 * 1024  # room for base64 images; text is capped by max_prompt_bytes
    max_prompt_bytes: int = 100 * 1024  # argv limit safety (Linux MAX_ARG_STRLEN is 128 KiB)
    rate_limit_per_minute: int = 60

    # policy
    single_user_personal_use: bool = False  # gates oauth_cli auth mode
    debug_log_prompts: bool = False
    default_max_budget_usd: float = 0.50  # reservation limit; Claude CLI also receives it as a per-run budget

    # "local" = in-process semaphores + rate limiter (single instance).
    # "redis" = shared across instances; needs PROXY_REDIS_URL and the `redis` package.
    queue_backend: str = "local"
    redis_url: str = ""

    # GET /metrics (Prometheus text format). Requires the admin token unless metrics_public is true.
    metrics_public: bool = False

    # images in requests (data: URLs / base64 only; remote URLs are never fetched)
    max_image_bytes: int = 5 * 1024 * 1024
    max_images: int = 8

    # env vars copied from the server env into the CLI env (network plumbing only; never secrets)
    cli_env_passthrough: str = "HTTPS_PROXY,HTTP_PROXY,NO_PROXY,ALL_PROXY,SSL_CERT_FILE,SSL_CERT_DIR,NODE_EXTRA_CA_CERTS"

    # directories the UI may serve
    frontend_dist: Path = Path("../frontend/dist")

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'proxy.db').resolve()}"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
