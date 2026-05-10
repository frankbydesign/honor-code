"""Auth endpoints: Google OAuth login, callback, /me, logout."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import config, sessions
from app.auth.deps import get_current_user
from app.auth.oauth import oauth
from app.db.models import User
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = config.OAUTH_REDIRECT_URI or str(
        request.url_for("auth_google_callback")
    )
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="auth_google_callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        # Authlib raises this on state mismatch, code reuse, network errors.
        logger.warning("google oauth failed: %s", exc.error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="oauth flow failed",
        )

    userinfo = token.get("userinfo")
    if userinfo is None:
        # Fallback: hit the userinfo endpoint directly.
        resp = await oauth.google.userinfo(token=token)
        userinfo = dict(resp)

    email = (userinfo.get("email") or "").lower()
    if not email or not userinfo.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="google did not return a verified email",
        )
    if email not in config.ALLOWED_EMAILS:
        logger.warning("denied login for unallowed email")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")

    google_sub = userinfo.get("sub")
    display_name = userinfo.get("name")

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(
            email=email,
            google_sub=google_sub,
            display_name=display_name,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.google_sub = google_sub or user.google_sub
        user.display_name = display_name or user.display_name
        user.last_login_at = now
    await db.flush()

    user_agent = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    session_row = await sessions.create_session(
        db,
        user_id=user.id,
        user_agent=user_agent,
        ip_address=ip,
    )

    response = RedirectResponse(url="/auth/me", status_code=status.HTTP_303_SEE_OTHER)
    sessions.set_session_cookie(response, session_row.id)
    return response


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "display_name": user.display_name}


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    await sessions.delete_session_by_cookie(db, request)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    sessions.clear_session_cookie(response)
    return response
