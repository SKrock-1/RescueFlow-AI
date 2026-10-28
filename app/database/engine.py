"""
RescueFlow AI — Database Engine & Session Management.

Provides the SQLAlchemy engine, session factory, and a context-manager
helper used by all tools and services.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in _settings.database_url else {},
)

# Enable WAL mode + foreign keys for SQLite
if "sqlite" in _settings.database_url:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a transactional database session and handle cleanup."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables (idempotent)."""
    from app.database.models import Base  # noqa: F811
    Base.metadata.create_all(bind=engine)
