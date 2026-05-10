"""FastAPI dependencies for authenticated routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import load_session
from app.db.models import User
from app.db.session import get_session


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
    return user
