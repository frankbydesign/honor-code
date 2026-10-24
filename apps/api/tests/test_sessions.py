"""Session lifecycle against the real SQLite engine.

load_session takes a Starlette Request, so these build a minimal real
Request from an ASGI scope rather than a fake object.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from app.auth import config, sessions
from app.db import models


def _request_with_cookie(value: str | None, path: str = "/api/auth/me") -> Request:
    headers = []
    if value is not None:
        headers.append(
            (b"cookie", f"{config.SESSION_COOKIE_NAME}={value}".encode("latin-1"))
        )
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("203.0.113.9", 4321),
        "server": ("test", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


async def _make_user(db, email: str = "sessions@example.com") -> models.User:
    user = models.User(email=email)
    db.add(user)
    await db.commit()
    return user


async def test_create_and_load_session(db):
    user = await _make_user(db)
    row = await sessions.create_session(
        db, user_id=user.id, user_agent="pytest", ip_address="203.0.113.9"
    )
    first_seen = row.last_seen_at
    first_expiry = row.expires_at
    assert first_expiry.tzinfo is not None

    token = sessions._sign(row.id)
    loaded = await sessions.load_session(db, _request_with_cookie(token))
    assert loaded is not None
    assert loaded.id == row.id
    assert loaded.user_id == user.id
    assert loaded.last_seen_at >= first_seen
    assert loaded.expires_at >= first_expiry
    # Sliding window: expiry is roughly TTL days from now, not from creation.
    assert loaded.expires_at > datetime.now(timezone.utc) + timedelta(
        days=config.SESSION_TTL_DAYS - 1
    )


async def test_expired_session_is_rejected(db):
    user = await _make_user(db)
    row = await sessions.create_session(db, user_id=user.id, user_agent=None, ip_address=None)
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()

    loaded = await sessions.load_session(db, _request_with_cookie(sessions._sign(row.id)))
    assert loaded is None


async def test_tampered_cookie_is_rejected_and_logged(db, caplog):
    user = await _make_user(db)
    row = await sessions.create_session(db, user_id=user.id, user_agent=None, ip_address=None)
    token = sessions._sign(row.id)
    flipped = ("A" if token[-1] != "A" else "B") + token[1:]

    with caplog.at_level(logging.WARNING, logger="app.auth.sessions"):
        loaded = await sessions.load_session(db, _request_with_cookie(flipped))

    assert loaded is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "a tampered cookie must be logged at WARNING"
    assert "tampered" in warnings[0].getMessage()
    assert token not in warnings[0].getMessage()
    assert flipped not in warnings[0].getMessage()


async def test_unknown_session_id_is_rejected(db):
    token = sessions._sign(uuid.uuid4())
    assert await sessions.load_session(db, _request_with_cookie(token)) is None


async def test_missing_cookie_is_rejected(db):
    assert await sessions.load_session(db, _request_with_cookie(None)) is None


async def test_delete_session_by_cookie(db):
    user = await _make_user(db)
    row = await sessions.create_session(db, user_id=user.id, user_agent=None, ip_address=None)
    token = sessions._sign(row.id)
    session_id = row.id

    await sessions.delete_session_by_cookie(db, _request_with_cookie(token))

    assert await sessions.load_session(db, _request_with_cookie(token)) is None
    db.expire_all()
    assert await db.get(models.Session, session_id) is None
