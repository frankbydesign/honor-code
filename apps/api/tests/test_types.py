"""UTCDateTime must give back aware UTC datetimes on SQLite.

SQLite has no timezone-aware column type, so a plain DateTime(timezone=True)
round-trips to a naive value and breaks every comparison against
datetime.now(timezone.utc). These tests pin the decorator that fixes it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import StatementError

from app.db import models


async def test_utc_datetime_round_trips_aware(db):
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    user = models.User(email="aware@example.com")
    db.add(user)
    await db.flush()
    session = models.Session(user_id=user.id, expires_at=expires)
    db.add(session)
    await db.commit()
    session_id = session.id

    db.expire_all()
    row = await db.get(models.Session, session_id)
    assert row is not None
    assert row.expires_at.tzinfo is not None
    # Must not raise "can't compare offset-naive and offset-aware datetimes".
    assert (row.expires_at <= datetime.now(timezone.utc)) is False
    assert row.expires_at == expires


async def test_utc_datetime_normalizes_other_zones(db):
    pacific = timezone(timedelta(hours=-7))
    local_time = datetime(2026, 10, 24, 9, 30, tzinfo=pacific)
    user = models.User(email="zones@example.com")
    db.add(user)
    await db.flush()
    session = models.Session(user_id=user.id, expires_at=local_time)
    db.add(session)
    await db.commit()
    session_id = session.id

    db.expire_all()
    row = await db.get(models.Session, session_id)
    assert row is not None
    assert row.expires_at.tzinfo == timezone.utc
    assert row.expires_at == local_time.astimezone(timezone.utc)
    assert row.expires_at.hour == 16


async def test_utc_datetime_refuses_naive_on_write(db):
    user = models.User(email="naive@example.com")
    db.add(user)
    await db.flush()
    db.add(models.Session(user_id=user.id, expires_at=datetime.now()))
    with pytest.raises(StatementError) as excinfo:
        await db.commit()
    assert isinstance(excinfo.value.orig, ValueError)
    await db.rollback()
