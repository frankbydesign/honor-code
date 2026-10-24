"""Application factory.

One process serves everything: the API under /api, and the built Angular
app from "/" when a build exists. During frontend development the Angular
dev server serves "/" itself and proxies /api here, so the static mount is
simply absent (no build directory) and nothing else changes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

# Importing these modules at startup is what makes the app fail fast if
# APP_BASE_URL, SESSION_SECRET, ENCRYPTION_KEY, or the Google values are
# missing or malformed.
from app.auth import config as auth_config
from app.auth.router import router as auth_router
from app.db.session import get_session
from app.security import token_crypto  # noqa: F401  (validates ENCRYPTION_KEY)

logger = logging.getLogger(__name__)

# apps/api/app/main.py -> parents[3] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]


def default_web_dist_dir() -> Path:
    return REPO_ROOT / "apps" / "web" / "dist" / "web" / "browser"


def web_dist_dir() -> Path:
    override = os.environ.get("WEB_DIST_DIR", "").strip()
    return Path(override).expanduser().resolve() if override else default_web_dist_dir()


class SPAStaticFiles(StaticFiles):
    """Static files with a single-page-app fallback.

    A request for a path that has no file extension and no matching file
    (an Angular route the user refreshed on, like /review/123) gets
    index.html. A request for something that looks like a file
    (/missing.png) stays a 404, so a broken asset reference is visible
    instead of quietly returning HTML.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not Path(path).suffix:
                return await super().get_response("index.html", scope)
            raise


def _build_api_router() -> APIRouter:
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

    # Registered last so it only matches what no real route did. Keeps every
    # /api/* miss a JSON 404 from the API instead of index.html from the
    # static mount's SPA fallback.
    @api.api_route("/{_unmatched:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def api_not_found(_unmatched: str):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    return api


def create_app() -> FastAPI:
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

    # API routes are registered before the static mount so /api/* always
    # resolves here; Starlette matches in registration order.
    app.include_router(_build_api_router())

    dist = web_dist_dir()
    if (dist / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="web")
        logger.info("serving frontend from %s", dist)
    else:
        logger.warning(
            "no frontend build at %s; serving the API only "
            "(run `pnpm build` in apps/web, or set WEB_DIST_DIR)",
            dist,
        )

    return app


app = create_app()
