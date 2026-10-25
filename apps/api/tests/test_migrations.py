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


ALL_TABLES = {
    "alembic_version",
    "sessions",
    "users",
    "source_documents",
    "sync_runs",
    "extraction_runs",
    "commitments",
    "status_events",
}


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_creates_tables(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    assert _tables(engine) == ALL_TABLES


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
    assert _tables(engine) == ALL_TABLES


def test_downgrade_one_step_keeps_phase0_tables(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001_initial")
    assert _tables(engine) == {"alembic_version", "sessions", "users"}


def test_source_documents_unique_per_user_kind_external_id(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    uniques = inspect(engine).get_unique_constraints("source_documents")
    assert any(set(u["column_names"]) == {"user_id", "kind", "external_id"} for u in uniques), uniques


@pytest.mark.parametrize(
    "table,column",
    [
        ("source_documents", "user_id"),
        ("extraction_runs", "document_id"),
        ("commitments", "document_id"),
        ("commitments", "run_id"),
        ("status_events", "commitment_id"),
    ],
)
def test_every_foreign_key_is_indexed(alembic_env, table, column):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    indexed = [ix["column_names"] for ix in inspect(engine).get_indexes(table)]
    assert [column] in indexed, f"{table}.{column} has no index: {indexed}"


def test_foreign_keys_cascade(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    for table in ("source_documents", "extraction_runs", "commitments", "status_events"):
        for fk in inspect(engine).get_foreign_keys(table):
            assert (fk.get("options") or {}).get("ondelete") == "CASCADE", (table, fk)


def test_migration_matches_models(alembic_env):
    cfg, engine = alembic_env
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"migration and models have drifted: {diff}"
