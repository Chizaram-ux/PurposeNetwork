"""Engine and session handling.

The engine is created on first use rather than at import time, so tests and the
CLI can point the app at a different database before anything connects.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import config

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def configure(url: Optional[str] = None, **kwargs) -> Engine:
    """Point the app at a database, replacing any existing engine."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url or config.database_url(), pool_pre_ping=True, **kwargs)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def engine() -> Engine:
    return _engine or configure()


def session_factory() -> sessionmaker:
    if _session_factory is None:
        configure()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that rolls back on error and always closes. Used by the CLI."""
    session = session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def create_all() -> None:
    from app.models import Base

    Base.metadata.create_all(engine())
