"""Alembic migrations run against a real SQLite file and match the models.

These use their own temporary database so they never interfere with the
suite-wide engine. Alembic re-executes env.py on every command, and env.py
reads DATABASE_URL at that moment, so monkeypatching the variable is enough.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_env(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    sync_engine = create_engine(f"sqlite:///{db_file}")
    yield cfg, sync_engine
    sync_engine.dispose()


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_creates_tables(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    assert _tables(engine) == {"alembic_version", "sessions", "users"}


def test_upgrade_is_idempotent(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    before = _tables(engine)
    command.upgrade(cfg, "head")
    assert _tables(engine) == before


def test_downgrade_removes_tables(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert _tables(engine) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert _tables(engine) == {"alembic_version", "sessions", "users"}


def test_migration_matches_models(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"migration and models have drifted: {diff}"
