from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

# Importing these modules at startup is what makes the app fail fast if
# APP_BASE_URL, SESSION_SECRET, ENCRYPTION_KEY, or the Google values are
# missing or malformed.
from app.auth import config as auth_config
from app.auth.router import router as auth_router
from app.db.session import get_session
from app.security import token_crypto  # noqa: F401  (validates ENCRYPTION_KEY)

app = FastAPI(title="Honor Code API")

# Authlib stashes the OAuth state parameter in this signed cookie between
# /login and /callback. Distinct cookie name from the app session. The
# Secure flag follows APP_BASE_URL like the session cookie does.
app.add_middleware(
    SessionMiddleware,
    secret_key=auth_config.SESSION_SECRET,
    session_cookie=auth_config.OAUTH_STATE_COOKIE_NAME,
    same_site="lax",
    https_only=auth_config.COOKIE_SECURE,
    max_age=10 * 60,
)

# Everything the frontend talks to lives under /api. The frontend itself is
# served from "/" (by this process once built, or by the Angular dev server
# proxying /api here), so there is one origin and no CORS layer.
api = APIRouter(prefix="/api")
api.include_router(auth_router)


@api.get("/health")
async def health(db: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        # Do not include the connection string or driver error details.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "database": "unreachable"},
        )
    return {"status": "ok", "database": "connected"}


app.include_router(api)
