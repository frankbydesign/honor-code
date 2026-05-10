from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

# Importing these modules at startup is what makes the app fail fast if
# SESSION_SECRET or ENCRYPTION_KEY (or the other required vars) are missing.
from app.auth import config as auth_config
from app.auth.router import router as auth_router
from app.db.session import get_session
from app.security import token_crypto  # noqa: F401  (validates ENCRYPTION_KEY)

app = FastAPI(title="Honor Code API")

# Explicit allowlist; no wildcards. allow_credentials=True is required so
# the browser sends the honor_code_session cookie on cross-origin fetches
# from the Vercel frontends.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(auth_config.FRONTEND_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# Authlib stashes the OAuth state parameter in this signed cookie between
# /login and /callback. Distinct cookie name from the app session.
app.add_middleware(
    SessionMiddleware,
    secret_key=auth_config.SESSION_SECRET,
    session_cookie=auth_config.OAUTH_STATE_COOKIE_NAME,
    same_site="lax",
    https_only=True,
    max_age=10 * 60,
)

app.include_router(auth_router)


@app.get("/health")
async def health(db: AsyncSession = Depends(get_session)) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        # Do not include the connection string or driver error details: those
        # may leak credentials. The status code + short message is enough for
        # an operator to know to check logs / Railway.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "database": "unreachable"},
        )
    return {"status": "ok", "database": "connected"}
