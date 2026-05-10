"""CORS allow-origin behavior with the pattern layer wired in.

We exercise the middleware via TestClient by issuing OPTIONS preflight
requests for the GET /auth/me endpoint with credentials.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "content-type",
    }


def test_preflight_from_exact_match_origin_is_allowed():
    resp = client.options("/auth/me", headers=_preflight_headers(
        "https://app.example.com"
    ))
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://app.example.com"
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_preflight_from_pattern_matched_origin_is_allowed():
    origin = "https://honor-code-4e3z8fp64-cpdigital.vercel.app"
    resp = client.options("/auth/me", headers=_preflight_headers(origin))
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_preflight_from_branch_alias_origin_is_allowed():
    origin = "https://honor-code-git-feat-login-ui-cpdigital.vercel.app"
    resp = client.options("/auth/me", headers=_preflight_headers(origin))
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin


def test_preflight_from_substring_team_attack_is_not_allowed():
    origin = "https://honor-code-X-cpdigitalevil.vercel.app"
    resp = client.options("/auth/me", headers=_preflight_headers(origin))
    # Starlette returns 400 for disallowed CORS preflights and omits
    # the access-control-allow-origin header.
    assert "access-control-allow-origin" not in resp.headers


def test_preflight_from_unrelated_origin_is_not_allowed():
    resp = client.options("/auth/me", headers=_preflight_headers(
        "https://evil.com"
    ))
    assert "access-control-allow-origin" not in resp.headers
