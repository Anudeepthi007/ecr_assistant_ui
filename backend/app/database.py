"""Database engine and session factory over the CSV data files.

The CSV files in ``DATA_DIR`` (``backend/data``) are the only place data lives.
``init_db()`` loads them into a working SQL copy at startup, so repositories,
agents and routes keep using ordinary SQLAlchemy queries, and every committed
change is written back to the matching CSV file (see :mod:`app.data.csv_store`).

The working copy is a throwaway SQLite file in the system temp folder, rebuilt
from the CSVs on every start. ``DATABASE_URL`` can point it somewhere else.
"""
from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.logging import get_logger

logger = get_logger("ecr.db")


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def _working_copy_url() -> str:
    if settings.database_url:
        return settings.database_url
    # One working copy per data folder, so two checkouts never share a file.
    digest = hashlib.sha1(str(Path(settings.data_dir).resolve()).encode("utf-8")).hexdigest()[:10]
    return f"sqlite:///{(Path(tempfile.gettempdir()) / f'ecr_assistant_{digest}.db').as_posix()}"


DATABASE_URL = _working_copy_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _make_engine():
    kwargs: dict = {"echo": settings.db_echo, "future": True, "pool_pre_ping": True}
    if IS_SQLITE:
        # check_same_thread=False: LangGraph nodes run in a worker thread pool.
        kwargs["connect_args"] = {"check_same_thread": False}
        if DATABASE_URL in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # one shared in-memory database
    return create_engine(DATABASE_URL, **kwargs)


engine = _make_engine()

if IS_SQLITE:  # keep FK constraints honest on SQLite too

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_connection, _record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager used by agents/background workers."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def enable_pgvector() -> bool:
    """Create the pgvector extension when the working copy is PostgreSQL."""
    if IS_SQLITE:
        return False
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        logger.info("pgvector.enabled")
        return True
    except Exception as exc:  # pragma: no cover - depends on server privileges
        logger.warning("pgvector.unavailable", error=str(exc))
        return False


_loaded_counts: dict[str, int] | None = None


def init_db(*, reload: bool = False) -> dict[str, int]:
    """Rebuild the working copy from the CSV files (once per process).

    Raises :class:`app.data.csv_store.CsvDataError` naming the file, line and
    column when a CSV cannot be loaded.
    """
    global _loaded_counts
    from app import models  # noqa: F401  (registers mappers)
    from app.data import csv_store

    if _loaded_counts is not None and not reload:
        return _loaded_counts
    csv_store.writer.flush()  # never drop tables with changes still unwritten
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        _loaded_counts = csv_store.load_all(db)
    csv_store.install_write_back(SessionLocal, engine)
    logger.info("database.loaded_from_csv", data_dir=settings.data_dir, working_copy=DATABASE_URL)
    return _loaded_counts
