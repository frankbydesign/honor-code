"""Regression tests from the decorrelated review of Task A.

Each test here reproduces a finding: a meeting removed while its
extraction is running, two stores of the same meeting at once, and two
coverage gaps (the document filter and a second user).
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select

from app.auth import config
from app.auth.oauth import oauth
from app.commitments import service
from app.commitments.extraction import ExtractionResult
from app.commitments.router import get_extractor
from app.db import models
from app.db.session import SessionLocal, engine
from app.main import app
from app.sources.fathom import FathomMeeting, to_meeting_input
from tests.conftest import load_fixture
from tests.fakes import candidate

QUOTE_SENTINEL = "ZQX-QUOTE-SENTINEL-99"


def _fixture_input(**update):
    meeting = FathomMeeting.model_validate(load_fixture("fathom/meeting_basic.json"))
    return to_meeting_input(meeting, meeting.transcript or []).model_copy(update=update)


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


class RemovingExtractor:
    """Removes the meeting from another session mid-call, then answers."""

    model = "fake-model"

    def __init__(self, user, document_id):
        self.user = user
        self.document_id = document_id

    async def extract(self, *, system, user):
        async with SessionLocal() as other:
            await service.remove_document(other, self.user, self.document_id)
        return ExtractionResult(
            raw={"commitments": [candidate(quote=QUOTE_SENTINEL, summary=QUOTE_SENTINEL)]},
            model=self.model,
            input_tokens=1,
            output_tokens=1,
        )


async def test_meeting_removed_during_extraction_is_404_and_leaks_nothing(
    signed_in_client, current_user, db, stored_meeting, caplog
):
    doc_id = stored_meeting.id
    app.dependency_overrides[get_extractor] = lambda: RemovingExtractor(current_user, doc_id)

    with caplog.at_level(logging.DEBUG, logger="app"):
        resp = await signed_in_client.post(f"/api/documents/{doc_id}/extract")

    assert resp.status_code == 404
    assert QUOTE_SENTINEL not in resp.text
    assert QUOTE_SENTINEL not in caplog.text
    assert await _count(db, models.Commitment) == 0


async def test_extraction_refuses_a_removed_meeting(current_user, db, stored_meeting, fake_extractor):
    doc_id = stored_meeting.id
    await service.remove_document(db, current_user, doc_id)
    doc = await db.get(models.SourceDocument, doc_id)
    with pytest.raises(service.NotFound):
        await service.run_extraction(db, doc, fake_extractor)
    assert fake_extractor.calls == []
    assert await _count(db, models.ExtractionRun) == 0


async def test_concurrent_stores_of_one_meeting_both_succeed(current_user):
    user_id = current_user.id

    async def store():
        async with SessionLocal() as s:
            user = await s.get(models.User, user_id)
            doc, created = await service.store_meeting(s, user, _fixture_input())
            return doc.id, created

    results = await asyncio.gather(store(), store())

    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    async with SessionLocal() as s:
        assert await _count(s, models.SourceDocument) == 1


def test_database_errors_never_include_row_values():
    # Backstop for the rule that transcript text never reaches a log: an
    # IntegrityError's message would otherwise list the bound parameters.
    assert engine.sync_engine.hide_parameters is True


async def test_document_filter_excludes_other_meetings(signed_in_client, current_user, db, stored_meeting, fake_extractor):
    other, _ = await service.store_meeting(db, current_user, _fixture_input(external_id="900002", title="Other call"))
    fake_extractor.returns([candidate(summary="From the first")])
    await signed_in_client.post(f"/api/documents/{stored_meeting.id}/extract")
    fake_extractor.returns([candidate(summary="From the other")])
    await signed_in_client.post(f"/api/documents/{other.id}/extract")

    resp = await signed_in_client.get("/api/commitments", params={"document_id": str(other.id)})
    assert [c["summary"] for c in resp.json()] == ["From the other"]


async def test_second_user_sees_none_of_the_first_users_data(
    signed_in_client, stored_meeting, fake_extractor, monkeypatch
):
    fake_extractor.returns([candidate()])
    cid = (await signed_in_client.post(f"/api/documents/{stored_meeting.id}/extract")).json()["commitments"][0]["id"]

    monkeypatch.setattr(config, "ALLOWED_EMAILS", frozenset({"test@example.com", "other@example.com"}))
    monkeypatch.setattr(
        oauth.google,
        "authorize_access_token",
        AsyncMock(return_value={"access_token": "x", "userinfo": {
            "email": "other@example.com", "email_verified": True, "sub": "google-sub-other", "name": "Other"}}),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as other:
        login = await other.get("/api/auth/google/callback", params={"code": "c", "state": "s"},
                                follow_redirects=False)
        assert login.status_code == 303

        assert (await other.get("/api/documents")).json() == []
        assert (await other.get("/api/commitments")).json() == []
        assert (await other.get(f"/api/documents/{stored_meeting.id}")).status_code == 404
        assert (await other.post(f"/api/documents/{stored_meeting.id}/extract")).status_code == 404
        assert (await other.delete(f"/api/documents/{stored_meeting.id}")).status_code == 404
        assert (await other.post(f"/api/commitments/{cid}/status", json={"to": "accepted"})).status_code == 404
        assert (await other.patch(f"/api/commitments/{cid}", json={"summary": "x"})).status_code == 404
        assert (await other.get(f"/api/commitments/{cid}/events")).status_code == 404

    item = (await signed_in_client.get("/api/commitments")).json()
    assert {c["status"] for c in item} == {"candidate"}
