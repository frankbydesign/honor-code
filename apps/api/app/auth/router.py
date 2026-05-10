"""Auth endpoints: Google OAuth login, callback, /me, logout."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import config, sessions
from app.auth.deps import get_current_user
from app.auth.oauth import oauth
from app.auth.origins import origin_matches
from app.db.models import User
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Key used to round-trip the post-login redirect target through Authlib's
# session cookie alongside Authlib's own state entry.
_NEXT_URL_SESSION_KEY = "post_login_next_url"


def _validate_next_url(next_url: str) -> str | None:
    """Return a sanitized next URL if its origin is in the allowlist.

    Path/query/fragment are preserved; only the origin (scheme+host+port)
    is matched against FRONTEND_ORIGINS and FRONTEND_ORIGINS_PATTERNS.
    Returns None for anything malformed or not allowlisted — callers
    treat None as "fall back".
    """
    try:
        parts = urlsplit(next_url)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    # Reject userinfo — `https://allowed.example.com@evil.com/` parses
    # to a netloc that includes `@evil.com`, and a permissive `*` in a
    # pattern could span the `@`. The browser would then navigate to
    # the post-`@` host. Easiest to refuse the whole URL.
    if "@" in parts.netloc:
        return None
    origin = f"{parts.scheme}://{parts.netloc}"
    if not origin_matches(
        origin, config.FRONTEND_ORIGINS, config.FRONTEND_ORIGINS_PATTERN_REGEX
    ):
        return None
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment)
    )


@router.get("/google/login")
async def google_login(
    request: Request,
    next: str | None = Query(default=None),
):
    if next is not None:
        validated = _validate_next_url(next)
        if validated is None:
            logger.warning("rejected login with disallowed next url")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="next url not in allowlist",
            )
        request.session[_NEXT_URL_SESSION_KEY] = validated
    else:
        request.session.pop(_NEXT_URL_SESSION_KEY, None)

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

    # Pop the next-url that was stashed during /google/login. Re-validate
    # because the allowlist may have changed between login and callback,
    # and to defend against any future bug that lets a bad value sneak in.
    raw_next = request.session.pop(_NEXT_URL_SESSION_KEY, None)
    redirect_target = "/auth/me"
    if raw_next:
        validated = _validate_next_url(raw_next)
        if validated is not None:
            redirect_target = validated

    response = RedirectResponse(
        url=redirect_target, status_code=status.HTTP_303_SEE_OTHER
    )
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
