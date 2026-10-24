"""HTTP-level tests for the auth routes under /api.

Google itself is mocked at the one seam that matters: Authlib's
authorize_access_token. Everything after that seam (allowlist, user upsert,
session row, cookie, redirect) is real and runs against SQLite.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from app.auth import config
from app.auth.oauth import oauth
from app.db import models

ALLOWED = "test@example.com"  # matches ALLOWED_EMAILS in conftest


def _userinfo(**overrides):
    info = {
        "email": ALLOWED,
        "email_verified": True,
        "sub": "google-sub-123",
        "name": "Test Person",
    }
    info.update(overrides)
    return info


def _mock_google(monkeypatch, userinfo):
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(return_value={"access_token": "x", "userinfo": userinfo}),
    )


async def _callback(client):
    return await client.get(
        "/api/auth/google/callback",
        params={"code": "fake-code", "state": "fake-state"},
        follow_redirects=False,
    )


def _session_cookie_header(resp) -> str | None:
    for header in resp.headers.get_list("set-cookie"):
        if header.startswith(f"{config.SESSION_COOKIE_NAME}="):
            return header
    return None


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_me_without_cookie_is_401(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_with_tampered_cookie_is_401(client):
    client.cookies.set(config.SESSION_COOKIE_NAME, "not-a-signed-token")
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_callback_creates_user_and_session_and_sets_cookie(client, db, monkeypatch):
    _mock_google(monkeypatch, _userinfo())

    resp = await _callback(client)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    cookie = _session_cookie_header(resp)
    assert cookie is not None
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "secure" not in lowered, "APP_BASE_URL is http in tests; cookie must not be Secure"

    user = (await db.execute(select(models.User))).scalar_one()
    assert user.email == ALLOWED
    assert user.google_sub == "google-sub-123"
    assert user.display_name == "Test Person"
    assert user.last_login_at is not None
    assert await _count(db, models.Session) == 1


async def test_callback_redirects_to_post_login_redirect_when_set(client, monkeypatch):
    _mock_google(monkeypatch, _userinfo())
    monkeypatch.setattr(config, "POST_LOGIN_REDIRECT", "http://localhost:4200/")

    resp = await _callback(client)

    assert resp.status_code == 303
    assert resp.headers["location"] == "http://localhost:4200/"


async def test_callback_rejects_email_not_in_allowlist(client, db, monkeypatch):
    _mock_google(monkeypatch, _userinfo(email="stranger@example.com"))

    resp = await _callback(client)

    assert resp.status_code == 403
    assert _session_cookie_header(resp) is None
    assert await _count(db, models.User) == 0
    assert await _count(db, models.Session) == 0


async def test_callback_allowlist_is_case_insensitive(client, db, monkeypatch):
    _mock_google(monkeypatch, _userinfo(email="Test@Example.COM"))

    resp = await _callback(client)

    assert resp.status_code == 303
    user = (await db.execute(select(models.User))).scalar_one()
    assert user.email == ALLOWED


async def test_callback_rejects_unverified_email(client, db, monkeypatch):
    _mock_google(monkeypatch, _userinfo(email_verified=False))

    resp = await _callback(client)

    assert resp.status_code == 400
    assert await _count(db, models.User) == 0
    assert await _count(db, models.Session) == 0


async def test_callback_second_login_updates_existing_user(client, db, monkeypatch):
    _mock_google(monkeypatch, _userinfo(name="First Name"))
    assert (await _callback(client)).status_code == 303
    first = (await db.execute(select(models.User))).scalar_one()
    first_login = first.last_login_at

    _mock_google(monkeypatch, _userinfo(name="Second Name"))
    assert (await _callback(client)).status_code == 303

    db.expire_all()
    users = (await db.execute(select(models.User))).scalars().all()
    assert len(users) == 1
    assert users[0].display_name == "Second Name"
    assert users[0].last_login_at >= first_login
    assert await _count(db, models.Session) == 2


async def test_me_after_login_returns_user(client, monkeypatch):
    _mock_google(monkeypatch, _userinfo())
    await _callback(client)

    resp = await client.get("/api/auth/me")

    assert resp.status_code == 200
    assert resp.json() == {"email": ALLOWED, "display_name": "Test Person"}


async def test_logout_returns_204_and_invalidates(client, db, monkeypatch):
    _mock_google(monkeypatch, _userinfo())
    await _callback(client)
    assert await _count(db, models.Session) == 1

    resp = await client.post("/api/auth/logout", follow_redirects=False)

    assert resp.status_code == 204
    assert resp.content == b""
    assert await _count(db, models.Session) == 0
    cleared = _session_cookie_header(resp)
    assert cleared is not None, "logout must send a clearing Set-Cookie"
    assert "max-age=0" in cleared.lower() or "expires=" in cleared.lower()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_session_is_revoked_when_email_leaves_allowlist(client, db, monkeypatch):
    _mock_google(monkeypatch, _userinfo())
    await _callback(client)
    assert (await client.get("/api/auth/me")).status_code == 200

    monkeypatch.setattr(config, "ALLOWED_EMAILS", frozenset({"someone-else@example.com"}))

    resp = await client.get("/api/auth/me")

    assert resp.status_code == 401
    assert await _count(db, models.Session) == 0, "the revoked session row must be deleted"
    # Even with the allowlist restored, the old cookie is dead.
    monkeypatch.setattr(config, "ALLOWED_EMAILS", frozenset({ALLOWED}))
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_cookies_are_secure_when_base_url_is_https(monkeypatch):
    """COOKIE_SECURE is derived at import; exercise the cookie writers directly."""
    from fastapi import Response

    from app.auth import sessions

    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    set_resp = Response()
    sessions.set_session_cookie(set_resp, uuid.uuid4())
    set_header = set_resp.headers["set-cookie"].lower()
    assert "secure" in set_header
    assert "httponly" in set_header
    assert "samesite=lax" in set_header

    clear_resp = Response()
    sessions.clear_session_cookie(clear_resp)
    assert "secure" in clear_resp.headers["set-cookie"].lower()


async def test_login_redirects_to_google_with_derived_redirect_uri(client):
    resp = await client.get("/api/auth/google/login", follow_redirects=False)

    assert resp.status_code == 302
    location = urlsplit(resp.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["redirect_uri"] == ["http://localhost:8000/api/auth/google/callback"]
    assert set(query["scope"][0].split()) >= {"openid", "email", "profile"}
    assert "state" in query


async def test_old_unprefixed_paths_are_gone(client):
    assert (await client.get("/auth/me")).status_code == 404
    assert (await client.get("/health")).status_code == 404
    assert (await client.get("/auth/google/login", follow_redirects=False)).status_code == 404


async def test_network_guard_is_armed(client):
    """Prove the guard works, and that the metadata seed is what keeps us offline."""
    oauth.google.server_metadata.pop("_loaded_at", None)
    with pytest.raises(RuntimeError, match="network call attempted"):
        await client.get("/api/auth/google/login", follow_redirects=False)
