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
    daily_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pricing_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Reservation(Base):
    __tablename__ = "reservations"
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    amount_usd: Mapped[float] = mapped_column(Float)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TopUp(Base):
    __tablename__ = "topups"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount_usd: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    """A local git repository workspace managed by AgentBridge Captain."""

    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    repo_path: Mapped[str] = mapped_column(String(1024))
    base_branch: Mapped[str] = mapped_column(String(128), default="main")
    captain_provider: Mapped[str] = mapped_column(String(64), default="")
    captain_model: Mapped[str] = mapped_column(String(128), default="")
    approval_mode: Mapped[str] = mapped_column(String(16), default="manual")  # manual | auto
    allowed_providers: Mapped[list] = mapped_column(JSON, default=list)  # empty => all enabled
    agent_roles: Mapped[dict] = mapped_column(JSON, default=dict)  # provider_name -> role description
    instructions: Mapped[str] = mapped_column(Text, default="")
    max_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    webhook_url: Mapped[str] = mapped_column(Text, default="")
    webhook_events: Mapped[list] = mapped_column(JSON, default=lambda: ["awaiting_approval", "needs_input", "completed", "failed"])
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Mission(Base):
    """One high-level order given to a project's Captain admin agent."""

    __tablename__ = "missions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="planning", index=True)
    captain_provider: Mapped[str] = mapped_column(String(64), default="")
    captain_model: Mapped[str] = mapped_column(String(128), default="")
    plan_summary: Mapped[str] = mapped_column(Text, default="")
    final_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MissionTask(Base):
    """One subtask delegated by the Captain to a connected CLI coding agent."""

    __tablename__ = "mission_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    provider_name: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    worktree_path: Mapped[str] = mapped_column(Text, default="")
    branch_name: Mapped[str] = mapped_column(String(160), default="")
    diff_stat: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MissionMessage(Base):
    """Unified communication log between user, Captain, and worker agents."""

    __tablename__ = "mission_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("mission_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    sender_type: Mapped[str] = mapped_column(String(16))  # user | captain | agent | system
    sender_name: Mapped[str] = mapped_column(String(64), default="")
    channel: Mapped[str] = mapped_column(String(24), default="dashboard")  # dashboard | cli | webhook | system
    kind: Mapped[str] = mapped_column(String(24), default="status")  # order | plan | status | question | reply | result | error
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
