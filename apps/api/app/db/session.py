"""Async SQLAlchemy engine, session factory, and FastAPI dependency.

The engine and session factory are module-level singletons so one pool is
shared across the process. Do not construct an engine per request.

DATABASE_URL defaults to a SQLite file under apps/api/data/. Two SQLite
specifics live here so nothing else has to know about them: the data
directory is created on demand (sqlite3 will not create it), and foreign
keys are switched on for every connection (SQLite leaves them off by
default, which would silently disable ON DELETE CASCADE).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/honor-code.db"


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def _ensure_sqlite_parent_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return
    database = parsed.database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def make_engine(url: str) -> AsyncEngine:
    _ensure_sqlite_parent_dir(url)
    engine = create_async_engine(url)

    if make_url(url).get_backend_name() == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


engine: AsyncEngine = make_engine(database_url())

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
