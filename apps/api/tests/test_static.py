"""FastAPI serves the built frontend from "/" without shadowing /api.

Each test builds a throwaway dist directory, points WEB_DIST_DIR at it, and
constructs a fresh app with create_app(), so the module-level app in
conftest (built without a dist directory) is untouched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.main import create_app

INDEX_MARKER = "<!-- honor-code-index -->"


@pytest.fixture
def dist_dir(tmp_path: Path) -> Path:
    dist = tmp_path / "dist" / "web" / "browser"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        f"<!doctype html><html><body>{INDEX_MARKER}<app-root></app-root></body></html>"
    )
    (dist / "main.js").write_bytes(b"console.log('honor code');")
    (dist / "assets" / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    return dist


async def _client_for(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def static_client(dist_dir: Path, monkeypatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("WEB_DIST_DIR", str(dist_dir))
    async for c in _client_for(create_app()):
        yield c


async def test_root_serves_index(static_client):
    resp = await static_client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert INDEX_MARKER in resp.text


async def test_asset_is_served(static_client):
    resp = await static_client.get("/main.js")
    assert resp.status_code == 200
    assert resp.content == b"console.log('honor code');"
    nested = await static_client.get("/assets/logo.svg")
    assert nested.status_code == 200
    assert "svg" in nested.headers["content-type"]


async def test_deep_link_falls_back_to_index(static_client):
    for path in ("/review", "/review/123", "/commitments/abc/edit"):
        resp = await static_client.get(path)
        assert resp.status_code == 200, path
        assert INDEX_MARKER in resp.text, path


async def test_missing_asset_is_404(static_client):
    resp = await static_client.get("/missing.png")
    assert resp.status_code == 404
    assert INDEX_MARKER not in resp.text
    resp = await static_client.get("/assets/nope.svg")
    assert resp.status_code == 404


async def test_api_is_not_shadowed(static_client):
    health = await static_client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    unknown = await static_client.get("/api/nope")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")
    assert INDEX_MARKER not in unknown.text

    me = await static_client.get("/api/auth/me")
    assert me.status_code == 401


async def test_head_requests_under_api_are_not_shadowed(static_client):
    """FastAPI does not add HEAD to GET routes, so without care a HEAD under
    /api falls through to the static mount and returns index.html with 200."""
    health = await static_client.head("/api/health")
    assert health.status_code == 200
    assert health.headers["content-type"].startswith("application/json")

    unknown = await static_client.head("/api/nope")
    assert unknown.status_code == 404
    assert not unknown.headers["content-type"].startswith("text/html")

    me = await static_client.head("/api/auth/me")
    assert me.status_code == 405
    assert not me.headers["content-type"].startswith("text/html")


async def test_bare_api_path_is_json_404(static_client):
    resp = await static_client.get("/api")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert INDEX_MARKER not in resp.text


async def test_wrong_method_on_api_route_is_405_in_both_modes(static_client, tmp_path: Path, monkeypatch):
    """A real route with the wrong method is 405 (with Allow), not 404, and the
    answer is the same whether or not a frontend build is mounted."""
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path / "does-not-exist"))
    api_only = create_app()

    async def check(c: httpx.AsyncClient) -> None:
        wrong = await c.post("/api/health")
        assert wrong.status_code == 405
        assert "GET" in wrong.headers["allow"]
        assert wrong.headers["content-type"].startswith("application/json")
        missing = await c.post("/api/nope")
        assert missing.status_code == 404

    await check(static_client)
    async for c in _client_for(api_only):
        await check(c)


async def test_catch_all_is_not_in_openapi(static_client):
    spec = (await static_client.get("/openapi.json")).json()
    assert not any("_unmatched" in path for path in spec["paths"]), list(spec["paths"])
    assert "/api/health" in spec["paths"]


async def test_index_html_is_never_cached_without_revalidation(static_client):
    """index.html names the hashed bundles of one build. A heuristically cached
    copy after a rebuild points at files that no longer exist (blank page)."""
    for path in ("/", "/review/123"):
        resp = await static_client.get(path)
        assert resp.status_code == 200, path
        assert resp.headers.get("cache-control") == "no-cache", path
    asset = await static_client.get("/main.js")
    assert asset.status_code == 200
    assert asset.headers.get("cache-control") != "no-cache"


async def test_app_starts_without_build_dir(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path / "does-not-exist"))
    with caplog.at_level("INFO", logger="app.main"):
        app = create_app()
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "no frontend build" in r.getMessage()]
    assert len(warnings) == 1, [r.getMessage() for r in caplog.records]

    async for c in _client_for(app):
        assert (await c.get("/api/health")).status_code == 200
        assert (await c.get("/")).status_code == 404


def test_default_dist_dir_points_at_apps_web(monkeypatch):
    monkeypatch.delenv("WEB_DIST_DIR", raising=False)
    from app.main import default_web_dist_dir

    p = default_web_dist_dir()
    assert p.is_absolute()
    assert p.parts[-4:] == ("web", "dist", "web", "browser")
    assert p.parents[3].name == "apps"
    assert (p.parents[3] / "api" / "alembic.ini").exists()
