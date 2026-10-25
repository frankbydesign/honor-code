"""Application factory.

One process serves everything: the API under /api, and the built Angular
app from "/" when a build exists. During frontend development the Angular
dev server serves "/" itself and proxies /api here, so the static mount is
simply absent (no build directory) and nothing else changes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Match
from starlette.staticfiles import StaticFiles

# Importing these modules at startup is what makes the app fail fast if
# APP_BASE_URL, SESSION_SECRET, ENCRYPTION_KEY, or the Google values are
# missing or malformed.
from app.auth import config as auth_config
from app import settings
from app.auth.router import router as auth_router
from app.commitments.router import router as commitments_router
from app.sync import service as sync_service
from app.sync.router import router as sync_router
from app.sync.scheduler import scheduler_loop
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


API_PREFIX = "/api"
_API_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class SPAStaticFiles(StaticFiles):
    """Static files with a single-page-app fallback.

    A request for a path that has no file extension and no matching file
    (an Angular route the user refreshed on, like /review/123) gets
    index.html. A request for something that looks like a file
    (/missing.png) stays a 404, so a broken asset reference is visible
    instead of quietly returning HTML.

    Nothing under /api is ever served from disk, whatever the method. The
    router answers every /api request it knows about before this mount is
    reached; anything that still arrives here is a miss.
    """

    async def get_response(self, path: str, scope):
        if path == API_PREFIX[1:] or path.startswith(API_PREFIX[1:] + "/"):
            raise StarletteHTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not Path(path).suffix:
                return await super().get_response("index.html", scope)
            raise

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        # index.html names the hashed bundles of one build. A copy the browser
        # kept on a heuristic lifetime would, after a rebuild, point at files
        # that no longer exist and render a blank page. no-cache still allows
        # the ETag round-trip, so the cost is one conditional request.
        if Path(full_path).name == "index.html":
            response.headers["Cache-Control"] = "no-cache"
        return response


def _build_api_router() -> APIRouter:
    api = APIRouter(prefix=API_PREFIX)
    api.include_router(auth_router)
    api.include_router(commitments_router)
    api.include_router(sync_router)

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

    # FastAPI does not add HEAD to GET routes, and a health probe is the one
    # endpoint something might reasonably HEAD. Separate registration keeps
    # the OpenAPI operation id unique.
    api.add_api_route("/health", health, methods=["HEAD"], include_in_schema=False)

    # Registered last, so it only matches what no real route did. Without it
    # an /api miss would reach the static mount, whose "/" is a full match for
    # everything; the router prefers a full match over a path-only (partial)
    # one, so the SPA fallback would answer with index.html. This handler
    # restores the answers the router gives when no mount is present: 405
    # with Allow when the path exists under another method, else 404.
    @api.api_route("/{_unmatched:path}", methods=_API_METHODS, include_in_schema=False)
    async def api_not_found(request: Request, _unmatched: str):
        allowed: set[str] = set()
        for route in request.app.router.routes:
            match, _ = route.matches(request.scope)
            if match is Match.PARTIAL:
                allowed.update(getattr(route, "methods", None) or ())
        if allowed:
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="Method Not Allowed",
                headers={"Allow": ", ".join(sorted(allowed))},
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    return api


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the Fathom sync loop when it is enabled and configured.

    The loop looks up run_scheduled_sync on each call, so it always runs
    the current settings. Shutdown cancels it.
    """
    task: asyncio.Task | None = None
    missing = settings.missing_for_sync()
    if not settings.sync_enabled():
        logger.info("automatic sync is off (SYNC_ENABLED=false)")
    elif missing:
        logger.warning("automatic sync is off: %s not set", ", ".join(missing))
    else:
        task = asyncio.create_task(
            scheduler_loop(
                lambda trigger: sync_service.run_scheduled_sync(trigger),
                interval_seconds=settings.fathom_sync_interval_minutes() * 60,
            ),
            name=sync_service.SCHEDULER_TASK_NAME,
        )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    # Optional Phase 1 settings; only malformed values stop startup.
    settings.validate()
    app = FastAPI(title="Honor Code API", lifespan=lifespan)

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
