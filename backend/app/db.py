from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def init_engine(url: str | None = None):
    global _engine, _SessionLocal
    url = url or get_settings().db_url
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(_engine)
    migrate(_engine)
    return _engine


# Columns added after 0.1.0. create_all() never alters an existing table, so add what is missing.
_ADDED_COLUMNS = {
    "api_keys": {"budget_usd": "FLOAT", "expires_at": "TIMESTAMP", "allowed_models": "JSON"},
    "ledger": {"key_id": "INTEGER"},
}


def migrate(engine) -> None:  # noqa: ANN001
    """Tiny forward-only migrations. Idempotent; safe to run on every start."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    if ddl == "TIMESTAMP" and engine.dialect.name == "postgresql":
                        ddl = "TIMESTAMP WITH TIME ZONE"
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        # ledger.user_id became nullable (admin test runs are recorded with no user)
        col = next(c for c in insp.get_columns("ledger") if c["name"] == "user_id")
        if not col["nullable"]:
            if engine.dialect.name == "sqlite":
                _sqlite_rebuild_ledger(conn)
            else:
                conn.execute(text("ALTER TABLE ledger ALTER COLUMN user_id DROP NOT NULL"))


def _sqlite_rebuild_ledger(conn) -> None:  # noqa: ANN001
    """SQLite cannot drop NOT NULL in place: rename, recreate from the model, copy, drop."""
    from .models import Ledger

    for (name,) in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='ledger' AND sql IS NOT NULL")).all():
        conn.execute(text(f'DROP INDEX "{name}"'))
    conn.execute(text("ALTER TABLE ledger RENAME TO ledger_old"))
    Ledger.__table__.create(conn)
    old = {r[1] for r in conn.execute(text("PRAGMA table_info(ledger_old)")).all()}
    cols = ", ".join(c.name for c in Ledger.__table__.columns if c.name in old)
    conn.execute(text(f"INSERT INTO ledger ({cols}) SELECT {cols} FROM ledger_old"))
    conn.execute(text("DROP TABLE ledger_old"))


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
