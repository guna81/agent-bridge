import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def as_utc(d: dt.datetime | None) -> dt.datetime | None:
    """SQLite drops tzinfo on read; every stored datetime is UTC, so re-attach it."""
    if d is None:
        return None
    return d.replace(tzinfo=dt.timezone.utc) if d.tzinfo is None else d.astimezone(dt.timezone.utc)


def iso_utc(d: dt.datetime | None) -> str | None:
    """ISO-8601 with an explicit +00:00 offset, so browsers don't read it as local time."""
    d = as_utc(d)
    return d.isoformat() if d else None


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    credits_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(100), default="")
    prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # per-key limits (all optional; None = unlimited)
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # lifetime spending cap for this key
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    allowed_models: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["claude/haiku", "agy/*"]


class Provider(Base):
    """One configured provider. `kind` selects the adapter: claude | agy | custom."""

    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)  # appears in model ids: name/model
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backend: Mapped[str] = mapped_column(String(16), default="cli")  # cli | direct
    binary_path: Mapped[str] = mapped_column(String(512), default="")
    default_model: Mapped[str] = mapped_column(String(128), default="")
    models: Mapped[list] = mapped_column(JSON, default=list)  # advertised model slugs
    mode: Mapped[str] = mapped_column(String(8), default="raw")  # raw | agent
    auth_mode: Mapped[str] = mapped_column(String(16), default="api_key")  # api_key | oauth_cli
    raw_system_prompt: Mapped[str] = mapped_column(Text, default="")
    skip_permissions: Mapped[bool] = mapped_column(Boolean, default=False)  # agent mode only
    use_host_home: Mapped[bool] = mapped_column(Boolean, default=False)  # reuse server user's CLI login
    max_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)  # custom CLI config, direct-API options
    api_key_enc: Mapped[str] = mapped_column(Text, default="")  # Fernet; shared provider-level key


class Ledger(Base):
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    # NULL user = an unbilled admin test run (Providers page "Test" button)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    key_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)  # for per-key budgets
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)  # tokens/cost estimated, not CLI-reported
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | aborted
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TopUp(Base):
    __tablename__ = "topups"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount_usd: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
