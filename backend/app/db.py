"""Database engine + session plumbing.

Synchronous SQLAlchemy on purpose. FastAPI runs plain ``def`` handlers in a
threadpool, and the worker pipeline runs in its own thread, so nothing here
ever blocks the event loop. It also keeps one code path for SQLite (dev) and
Postgres (prod) — see ``docs/deployment.md``.
"""
import os
from typing import Iterator
from urllib.parse import urlparse

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite will not create intermediate directories for us."""
    path = url.split("///", 1)[-1]
    if path and path != ":memory:":
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)


_connect_args = {}
if settings.is_sqlite:
    _ensure_sqlite_dir(settings.database_url)
    # The worker thread and request threads share the engine.
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        # WAL lets the worker thread write while requests read.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if absent.

    v1 ships ``create_all`` rather than Alembic deliberately: §9 requires that
    every v2 table already exist in v1, so the first real migration is additive
    columns only. Introduce Alembic before the first production deploy.
    """
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)


def database_flavour() -> str:
    return urlparse(settings.database_url).scheme.split("+")[0]
