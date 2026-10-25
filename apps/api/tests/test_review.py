"""Review: status transitions, edits, and the commitments list."""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import select

from app.db import models
from tests.fakes import candidate

STATUSES = ["candidate", "accepted", "rejected", "done", "dropped"]
ALLOWED = {
    ("candidate", "accepted"),
    ("candidate", "rejected"),
    ("accepted", "done"),
    ("accepted", "dropped"),
    ("rejected", "candidate"),
    ("done", "accepted"),
    ("dropped", "accepted"),
}
# Shortest path from "candidate" to each status, through allowed moves.
PATH = {
    "candidate": [],
    "accepted": ["accepted"],
    "rejected": ["rejected"],
    "done": ["accepted", "done"],
    "dropped": ["accepted", "dropped"],
}


async def _one_candidate(client, doc_id, fake, **overrides) -> str:
    fake.returns([candidate(**overrides)])
    resp = await client.post(f"/api/documents/{doc_id}/extract")
    assert resp.status_code == 201
    return resp.json()["commitments"][0]["id"]


async def _move(client, cid, to, note=None):
    body = {"to": to} if note is None else {"to": to, "note": note}
    return await client.post(f"/api/commitments/{cid}/status", json=body)


async def _walk_to(client, cid, status):
    for step in PATH[status]:
        assert (await _move(client, cid, step)).status_code == 200


async def _events(client, cid):
    resp = await client.get(f"/api/commitments/{cid}/events")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize("src,dst", sorted(ALLOWED))
async def test_allowed_transition(signed_in_client, stored_meeting, fake_extractor, src, dst):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    await _walk_to(signed_in_client, cid, src)
    before = len(await _events(signed_in_client, cid))

    resp = await _move(signed_in_client, cid, dst)

    assert resp.status_code == 200
    assert resp.json()["status"] == dst
    events = await _events(signed_in_client, cid)
    assert len(events) == before + 1
    assert events[-1]["from_status"] == src and events[-1]["to_status"] == dst


@pytest.mark.parametrize(
    "src,dst", [p for p in itertools.product(STATUSES, STATUSES) if p not in ALLOWED]
)
async def test_disallowed_transition_is_409(signed_in_client, stored_meeting, fake_extractor, src, dst):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    await _walk_to(signed_in_client, cid, src)
    before = len(await _events(signed_in_client, cid))

    resp = await _move(signed_in_client, cid, dst)

    assert resp.status_code == 409
    assert len(await _events(signed_in_client, cid)) == before


async def test_drop_note_is_kept(signed_in_client, stored_meeting, fake_extractor):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    await _move(signed_in_client, cid, "accepted")
    await _move(signed_in_client, cid, "dropped", note="Alice said it is no longer needed")
    assert (await _events(signed_in_client, cid))[-1]["note"] == "Alice said it is no longer needed"


async def test_unknown_status_in_transition_is_422(signed_in_client, stored_meeting, fake_extractor):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    assert (await _move(signed_in_client, cid, "archived")).status_code == 422


@pytest.mark.parametrize("status", ["candidate", "accepted"])
async def test_patch_edits_open_commitments(signed_in_client, stored_meeting, fake_extractor, status):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    await _walk_to(signed_in_client, cid, status)

    resp = await signed_in_client.patch(
        f"/api/commitments/{cid}",
        json={"summary": "Send Alice the Q4 budget", "counterparty": "Alice", "due_text": "Friday",
              "due_on": "2026-10-23", "details": "Use the new template", "strength": "soft"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "Send Alice the Q4 budget"
    assert body["counterparty"] == "Alice"
    assert body["due_on"] == "2026-10-23"
    assert body["strength"] == "soft"
    assert body["quote"] == candidate()["quote"]


async def test_patch_can_clear_a_field(signed_in_client, stored_meeting, fake_extractor):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    resp = await signed_in_client.patch(f"/api/commitments/{cid}", json={"due_on": None, "due_text": None})
    assert resp.status_code == 200
    assert resp.json()["due_on"] is None and resp.json()["due_text"] is None


@pytest.mark.parametrize("field", ["quote", "speaker", "status", "quote_found"])
async def test_patch_rejects_read_only_fields(signed_in_client, stored_meeting, fake_extractor, field):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    resp = await signed_in_client.patch(f"/api/commitments/{cid}", json={field: "x"})
    assert resp.status_code == 422


async def test_patch_rejects_empty_summary(signed_in_client, stored_meeting, fake_extractor):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    assert (await signed_in_client.patch(f"/api/commitments/{cid}", json={"summary": "  "})).status_code == 422


@pytest.mark.parametrize("status", ["rejected", "done", "dropped"])
async def test_patch_closed_commitment_is_409(signed_in_client, stored_meeting, fake_extractor, status):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    await _walk_to(signed_in_client, cid, status)
    resp = await signed_in_client.patch(f"/api/commitments/{cid}", json={"summary": "changed"})
    assert resp.status_code == 409


async def test_list_filters(signed_in_client, stored_meeting, fake_extractor):
    fake_extractor.returns([
        candidate(summary="A", counterparty="Alice Kim"),
        candidate(summary="B", counterparty="Jordan"),
        candidate(summary="C", counterparty=None),
    ])
    items = (await signed_in_client.post(f"/api/documents/{stored_meeting.id}/extract")).json()["commitments"]
    await _move(signed_in_client, items[0]["id"], "accepted")

    def summaries(resp):
        assert resp.status_code == 200
        return sorted(c["summary"] for c in resp.json())

    assert summaries(await signed_in_client.get("/api/commitments")) == ["A", "B", "C"]
    assert summaries(await signed_in_client.get("/api/commitments", params={"status": "candidate"})) == ["B", "C"]
    assert summaries(await signed_in_client.get("/api/commitments", params={"status": "accepted"})) == ["A"]
    assert summaries(await signed_in_client.get("/api/commitments", params={"counterparty": "Jordan"})) == ["B"]
    assert summaries(
        await signed_in_client.get("/api/commitments", params={"document_id": str(stored_meeting.id)})
    ) == ["A", "B", "C"]


async def test_list_unknown_status_is_422(signed_in_client):
    assert (await signed_in_client.get("/api/commitments", params={"status": "archived"})).status_code == 422


async def test_list_items_embed_document(signed_in_client, stored_meeting, fake_extractor):
    await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    item = (await signed_in_client.get("/api/commitments")).json()[0]
    assert item["document"] == {"id": str(stored_meeting.id), "title": "Budget check-in", "occurred_on": "2026-10-20"}


async def test_unknown_commitment_is_404(signed_in_client):
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await _move(signed_in_client, missing, "accepted")).status_code == 404
    assert (await signed_in_client.patch(f"/api/commitments/{missing}", json={"summary": "x"})).status_code == 404


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/documents", None),
        ("GET", "/api/documents/{doc}", None),
        ("DELETE", "/api/documents/{doc}", None),
        ("POST", "/api/documents/{doc}/extract", None),
        ("GET", "/api/commitments", None),
        ("PATCH", "/api/commitments/{cid}", {"summary": "x"}),
        ("POST", "/api/commitments/{cid}/status", {"to": "accepted"}),
        ("GET", "/api/commitments/{cid}/events", None),
    ],
)
async def test_every_endpoint_requires_session(signed_in_client, db, stored_meeting, fake_extractor, method, path, body):
    cid = await _one_candidate(signed_in_client, stored_meeting.id, fake_extractor)
    signed_in_client.cookies.clear()
    url = path.format(doc=stored_meeting.id, cid=cid)
    resp = await signed_in_client.request(method, url, json=body)
    assert resp.status_code == 401
    # Nothing changed behind the 401.
    row = (await db.execute(select(models.Commitment))).scalar_one()
    assert row.status == "candidate" and row.summary == candidate()["summary"]
