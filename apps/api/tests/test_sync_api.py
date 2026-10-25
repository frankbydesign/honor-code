"""GET and POST /api/sync, and whether the app starts the scheduler."""

from __future__ import annotations

import asyncio

import pytest

from app.commitments.router import get_extractor
from app.main import app
from app.sync import service as sync_service
from app.sync.router import get_meeting_source
from tests.fakes import candidate, fathom_fixture_source


@pytest.fixture
def configured(monkeypatch, fake_extractor):
    monkeypatch.setenv("FATHOM_API_KEY", "fathom-test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    source = fathom_fixture_source()
    app.dependency_overrides[get_meeting_source] = lambda: source
    app.dependency_overrides[get_extractor] = lambda: fake_extractor
    return source


async def _wait_idle():
    await asyncio.wait_for(sync_service.wait_until_idle(), timeout=5)


async def test_sync_status_requires_session(client):
    assert (await client.get("/api/sync")).status_code == 401
    assert (await client.post("/api/sync")).status_code == 401


async def test_sync_status_names_missing_keys(signed_in_client):
    body = (await signed_in_client.get("/api/sync")).json()
    assert body == {
        "configured": False,
        "missing": ["FATHOM_API_KEY", "ANTHROPIC_API_KEY"],
        "running": False,
        "last_run": None,
    }


async def test_sync_now_without_keys_is_503(signed_in_client):
    resp = await signed_in_client.post("/api/sync")
    assert resp.status_code == 503
    assert "FATHOM_API_KEY" in resp.json()["detail"]
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


async def test_sync_now_starts_a_sync_and_reports_it(signed_in_client, configured, fake_extractor):
    fake_extractor.returns([candidate()])

    resp = await signed_in_client.post("/api/sync")
    assert resp.status_code == 202
    started = resp.json()["run"]
    assert started["trigger"] == "manual"
    assert started["status"] == "running"

    await _wait_idle()
    status = (await signed_in_client.get("/api/sync")).json()
    assert status["configured"] is True
    assert status["missing"] == []
    assert status["running"] is False
    assert status["last_run"]["id"] == started["id"]
    assert status["last_run"]["status"] == "succeeded"
    assert status["last_run"]["meetings_new"] == 3

    docs = (await signed_in_client.get("/api/documents")).json()
    assert len(docs) == 3
    assert sum(d["counts"]["candidate"] for d in docs) == 3


async def test_sync_now_while_running_is_409(signed_in_client, configured):
    configured.gate = asyncio.Event()
    first = await signed_in_client.post("/api/sync")
    assert first.status_code == 202
    assert (await signed_in_client.get("/api/sync")).json()["running"] is True

    second = await signed_in_client.post("/api/sync")
    assert second.status_code == 409

    configured.gate.set()
    await _wait_idle()


async def test_status_never_contains_keys(signed_in_client, configured):
    await signed_in_client.post("/api/sync")
    await _wait_idle()
    text = (await signed_in_client.get("/api/sync")).text
    assert "fathom-test-key" not in text and "anthropic-test-key" not in text


def _scheduler_tasks():
    return [t for t in asyncio.all_tasks() if t.get_name() == sync_service.SCHEDULER_TASK_NAME and not t.done()]


async def test_lifespan_skips_scheduler_when_disabled(monkeypatch):
    monkeypatch.setenv("FATHOM_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("SYNC_ENABLED", "false")
    async with app.router.lifespan_context(app):
        assert _scheduler_tasks() == []


async def test_lifespan_skips_scheduler_when_not_configured(monkeypatch):
    monkeypatch.setenv("SYNC_ENABLED", "true")
    async with app.router.lifespan_context(app):
        assert _scheduler_tasks() == []


async def test_lifespan_starts_and_stops_scheduler_when_configured(monkeypatch):
    monkeypatch.setenv("FATHOM_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("SYNC_ENABLED", "true")
    calls = []

    async def fake_run(trigger):
        calls.append(trigger)

    monkeypatch.setattr(sync_service, "run_scheduled_sync", fake_run)
    async with app.router.lifespan_context(app):
        assert len(_scheduler_tasks()) == 1
    await asyncio.sleep(0)
    assert _scheduler_tasks() == []


async def test_startup_marks_interrupted_runs_failed(db, monkeypatch):
    """Rows left 'running' by a quit mid-sync or mid-extraction are closed at startup."""
    from datetime import datetime, timezone

    from app.db import models

    monkeypatch.setenv("SYNC_ENABLED", "false")
    started = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    user = models.User(email="test@example.com")
    db.add(user)
    await db.flush()
    doc = models.SourceDocument(
        user_id=user.id, kind="fathom_meeting", external_id="1", title="t", occurred_at=started,
        occurred_on=started.date(), raw_text="", segments=[], speakers=[], char_count=0,
    )
    db.add(doc)
    await db.flush()
    db.add(models.SyncRun(source="fathom", trigger="startup", status="running", window_start=started, started_at=started))
    db.add(models.SyncRun(source="fathom", trigger="manual", status="succeeded", window_start=started,
                          started_at=started, finished_at=started))
    db.add(models.ExtractionRun(document_id=doc.id, status="running", model="m", prompt_version="v1", started_at=started))
    await db.commit()

    async with app.router.lifespan_context(app):
        pass

    db.expunge_all()
    from sqlalchemy import select

    syncs = {r.trigger: r for r in (await db.execute(select(models.SyncRun))).scalars()}
    assert syncs["startup"].status == "failed" and syncs["startup"].error == "interrupted"
    assert syncs["startup"].finished_at is not None
    assert syncs["manual"].status == "succeeded" and syncs["manual"].error is None
    run = (await db.execute(select(models.ExtractionRun))).scalar_one()
    assert run.status == "failed" and run.error == "interrupted"
