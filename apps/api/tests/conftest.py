"""Test configuration for the Honor Code API.

Order matters here. Every `app.*` module validates its environment at import
time, and `app.db.session` builds the engine at import time, so the env vars
below are set before anything from `app` is imported. They are assigned, not
defaulted, so a DATABASE_URL exported in the shell can never be the one the
suite truncates between tests. Tests that need a
different configuration (the startup validators) run in subprocesses instead.

The suite never touches the network: Authlib's Google client is seeded with
its discovery metadata so no fetch happens, and a guard on httpx's real
transport turns any escape into a loud failure.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from collections.abc import AsyncIterator

from cryptography.fernet import Fernet

_TEST_DIR = tempfile.mkdtemp(prefix="honor-code-test-")

_DEFAULTS = {
    "DATABASE_URL": f"sqlite+aiosqlite:///{_TEST_DIR}/test.db",
    "APP_BASE_URL": "http://localhost:8000",
    "SESSION_SECRET": secrets.token_urlsafe(48),
    "ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "ALLOWED_EMAILS": "test@example.com",
    # The suite-wide app is API-only. Pointing this at a path that does not
    # exist keeps the suite independent of whether `pnpm build` has run in
    # this checkout; test_static.py builds its own app with a real dist dir.
    "WEB_DIST_DIR": f"{_TEST_DIR}/no-frontend-build",
}
# Assigned unconditionally, never setdefault: an exported DATABASE_URL in the
# shell would otherwise make the suite run (and wipe tables) against it.
for _key, _value in _DEFAULTS.items():
    os.environ[_key] = _value
for _stale in ("POST_LOGIN_REDIRECT", "FRONTEND_ORIGINS", "FRONTEND_ORIGINS_PATTERNS", "OAUTH_REDIRECT_URI"):
    os.environ.pop(_stale, None)

# Only now is it safe to import the application.
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.auth.oauth import oauth  # noqa: E402
from app.db import models  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

# Authlib fetches the OIDC discovery document lazily unless this key is
# present. Seeding it keeps /api/auth/google/login fully offline.
GOOGLE_METADATA = {
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    "issuer": "https://accounts.google.com",
    "_loaded_at": 1,
}


@pytest.fixture(autouse=True)
def _seed_google_metadata():
    oauth.google.server_metadata.update(GOOGLE_METADATA)
    yield
    oauth.google.server_metadata.update(GOOGLE_METADATA)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if anything tries to leave the process.

    Patched on the real-network transport only; the test client below uses
    ASGITransport, which is a different class and is unaffected.
    """

    async def deny(self, request):  # noqa: ANN001
        raise RuntimeError(f"network call attempted in tests: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny)


@pytest_asyncio.fixture(autouse=True, scope="session")
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    yield
    async with SessionLocal() as session:
        await session.execute(delete(models.Session))
        await session.execute(delete(models.User))
        await session.commit()


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
