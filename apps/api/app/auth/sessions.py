"""Session lifecycle: create, lookup, slide expiry, delete.

A session row's UUID is signed with itsdangerous and that signed token
is what lives in the cookie. Verification is two stages: signature
first (tamper detection => log + 401), then DB lookup (expired or
missing => 401, no log noise).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import config
from app.db.models import Session as SessionModel

logger = logging.getLogger(__name__)

_serializer = URLSafeSerializer(config.SESSION_SECRET, salt="honor-code-session")


def _sign(session_id: uuid.UUID) -> str:
    return _serializer.dumps(str(session_id))


def _unsign(token: str) -> uuid.UUID:
    """Returns the session UUID, or raises BadSignature / ValueError."""
    raw = _serializer.loads(token)
    return uuid.UUID(raw)


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_agent: str | None,
    ip_address: str | None,
) -> SessionModel:
    expires_at = datetime.now(timezone.utc) + timedelta(days=config.SESSION_TTL_DAYS)
    row = SessionModel(
        user_id=user_id,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def load_session(db: AsyncSession, request: Request) -> SessionModel | None:
    """Validate the cookie and return the session row, or None.

    Returns None for any of: no cookie, bad signature, unknown id,
    expired session. Bad-signature requests are logged at WARNING; the
    others are silent.
    """
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not token:
        return None

    try:
        session_id = _unsign(token)
    except (BadSignature, ValueError):
        client = request.client.host if request.client else "unknown"
        logger.warning(
            "rejected tampered session cookie from %s on %s", client, request.url.path
        )
        return None

    row = await db.get(SessionModel, session_id)
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    if row.expires_at <= now:
        return None

    # Sliding window: bump expiry and last_seen on every authenticated hit.
    row.last_seen_at = now
    row.expires_at = now + timedelta(days=config.SESSION_TTL_DAYS)
    await db.commit()
    return row


async def delete_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    await db.execute(delete(SessionModel).where(SessionModel.id == session_id))
    await db.commit()


async def delete_session_by_cookie(db: AsyncSession, request: Request) -> None:
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not token:
        return
    try:
        session_id = _unsign(token)
    except (BadSignature, ValueError):
        return
    await delete_session(db, session_id)


def set_session_cookie(response: Response, session_id: uuid.UUID) -> None:
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=_sign(session_id),
        max_age=config.SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )
