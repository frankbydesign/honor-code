"""Stored meetings: the service that creates them and the API that lists them."""

from __future__ import annotations

from sqlalchemy import func, select

from app.commitments.service import store_meeting
from app.db import models
from app.sources.fathom import FathomMeeting, to_meeting_input
from tests.conftest import load_fixture
from tests.fakes import candidate


def _fixture_input():
    meeting = FathomMeeting.model_validate(load_fixture("fathom/meeting_basic.json"))
    return to_meeting_input(meeting, meeting.transcript or [])


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_store_meeting_twice_keeps_one_row(current_user, db):
    first, created_first = await store_meeting(db, current_user, _fixture_input())
    second, created_second = await store_meeting(db, current_user, _fixture_input())
    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert await _count(db, models.SourceDocument) == 1


async def test_stored_meeting_fields(stored_meeting):
    doc = stored_meeting
    assert doc.kind == "fathom_meeting"
    assert doc.external_id == "900001"
    assert doc.title == "Budget check-in"
    assert doc.occurred_on.isoformat() == "2026-10-20"  # local date, not the UTC 21st
    assert doc.my_speaker == "Frank E."
    assert doc.speakers == ["Alice Kim", "Frank E."]
    assert doc.char_count == len(doc.raw_text)
    assert doc.raw_text.startswith("[00:00:04] Alice Kim: ")
    assert doc.vendor_action_items[0]["assignee"]["email"] == "frank@example.com"


async def test_list_documents_requires_session(client):
    assert (await client.get("/api/documents")).status_code == 401


async def test_list_documents_shows_zeroed_counts(signed_in_client, stored_meeting):
    resp = await signed_in_client.get("/api/documents")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == str(stored_meeting.id)
    assert items[0]["title"] == "Budget check-in"
    assert items[0]["occurred_on"] == "2026-10-20"
    assert items[0]["counts"] == {"candidate": 0, "accepted": 0, "done": 0, "rejected": 0, "dropped": 0}


async def test_list_documents_newest_first(signed_in_client, current_user, db, stored_meeting):
    newer = _fixture_input().model_copy(
        update={"external_id": "900002", "title": "Later call",
                "occurred_at": stored_meeting.occurred_at.replace(day=23)}
    )
    await store_meeting(db, current_user, newer)
    titles = [d["title"] for d in (await signed_in_client.get("/api/documents")).json()]
    assert titles == ["Later call", "Budget check-in"]


async def test_counts_reflect_statuses_after_extraction(signed_in_client, stored_meeting, fake_extractor):
    fake_extractor.returns([candidate(), candidate(summary="Look at the volunteer form", strength="soft")])
    resp = await signed_in_client.post(f"/api/documents/{stored_meeting.id}/extract")
    assert resp.status_code == 201
    first_id = resp.json()["commitments"][0]["id"]
    await signed_in_client.post(f"/api/commitments/{first_id}/status", json={"to": "accepted"})

    counts = (await signed_in_client.get("/api/documents")).json()[0]["counts"]
    assert counts == {"candidate": 1, "accepted": 1, "done": 0, "rejected": 0, "dropped": 0}


async def test_get_document_detail(signed_in_client, stored_meeting, fake_extractor):
    fake_extractor.returns([candidate()])
    await signed_in_client.post(f"/api/documents/{stored_meeting.id}/extract")

    resp = await signed_in_client.get(f"/api/documents/{stored_meeting.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_text"] == stored_meeting.raw_text
    assert body["speakers"] == ["Alice Kim", "Frank E."]
    assert body["my_speaker"] == "Frank E."
    assert body["source_url"] == "https://fathom.video/share/invented-token-900001"
    assert len(body["runs"]) == 1 and body["runs"][0]["status"] == "succeeded"
    assert len(body["commitments"]) == 1


async def test_get_unknown_document_is_404(signed_in_client):
    resp = await signed_in_client.get("/api/documents/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_remove_document_leaves_tombstone(signed_in_client, current_user, db, stored_meeting, fake_extractor):
    doc_id = stored_meeting.id
    fake_extractor.returns([candidate()])
    await signed_in_client.post(f"/api/documents/{doc_id}/extract")

    resp = await signed_in_client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 204

    assert await _count(db, models.ExtractionRun) == 0
    assert await _count(db, models.Commitment) == 0
    assert await _count(db, models.StatusEvent) == 0
    db.expunge_all()  # fresh reads below; already-loaded fixtures stay usable
    doc = await db.get(models.SourceDocument, doc_id)
    assert doc.raw_text == ""
    assert doc.segments == []
    assert doc.removed_at is not None

    assert (await signed_in_client.get("/api/documents")).json() == []
    assert (await signed_in_client.get(f"/api/documents/{doc_id}")).status_code == 404

    # A later sync offering the same meeting finds it already stored.
    _, created = await store_meeting(db, current_user, _fixture_input())
    assert created is False

    assert (await signed_in_client.delete(f"/api/documents/{doc_id}")).status_code == 404


async def test_extract_on_removed_document_is_404(signed_in_client, stored_meeting, fake_extractor):
    await signed_in_client.delete(f"/api/documents/{stored_meeting.id}")
    resp = await signed_in_client.post(f"/api/documents/{stored_meeting.id}/extract")
    assert resp.status_code == 404
    assert fake_extractor.calls == []
