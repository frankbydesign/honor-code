"""Engine construction and the SQLite-specific behaviors we depend on."""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select, text

from app.db import models
from app.db.session import API_DIR, DEFAULT_DATABASE_URL, make_engine


async def test_data_directory_is_created(tmp_path: Path):
    target = tmp_path / "nested" / "deeper" / "honor-code.db"
    assert not target.parent.exists()

    engine = make_engine(f"sqlite+aiosqlite:///{target}")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()

    assert target.parent.is_dir()
    assert target.exists()


async def test_foreign_keys_enforced(db):
    user = models.User(email="cascade@example.com")
    db.add(user)
    await db.flush()
    from datetime import datetime, timedelta, timezone

    db.add(
        models.Session(
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    await db.commit()

    await db.execute(text("DELETE FROM users"))
    await db.commit()

    remaining = (
        await db.execute(select(func.count()).select_from(models.Session))
    ).scalar_one()
    assert remaining == 0, "ON DELETE CASCADE did nothing: PRAGMA foreign_keys is off"


async def test_uuid_primary_keys_are_uuid_objects(db):
    user = models.User(email="uuid@example.com")
    db.add(user)
    await db.commit()
    assert isinstance(user.id, uuid.UUID)
    user_id = user.id

    db.expire_all()
    fetched = await db.get(models.User, user_id)
    assert fetched is not None
    assert isinstance(fetched.id, uuid.UUID)
    assert fetched.id == user_id


async def test_health_reports_connected(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "connected"}


def test_default_database_url_is_anchored_to_api_dir():
    assert DEFAULT_DATABASE_URL.startswith("sqlite+aiosqlite:////"), DEFAULT_DATABASE_URL
    assert DEFAULT_DATABASE_URL.endswith("/data/honor-code.db")
    assert str(API_DIR / "data" / "honor-code.db") in DEFAULT_DATABASE_URL
    assert API_DIR.name == "api" and API_DIR.parent.name == "apps"
    assert (API_DIR / "alembic.ini").exists()
