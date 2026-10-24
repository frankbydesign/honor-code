"""FastAPI dependencies for authenticated routes."""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import config
from app.auth.sessions import delete_session, load_session
from app.db.models import User
from app.db.session import get_session

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    session = await load_session(db, request)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = await db.get(User, session.user_id)
    if user is None:
        # Session row outlived its user somehow. Treat as logged out.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    if user.email.lower() not in config.ALLOWED_EMAILS:
        # Removed from the allowlist after logging in: the sliding expiry
        # would otherwise keep this session alive indefinitely.
        logger.warning("ending session for email no longer in ALLOWED_EMAILS")
        await delete_session(db, session.id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user
