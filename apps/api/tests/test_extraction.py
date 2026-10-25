"""Extraction runs: one model call per run, all or nothing.

The model is replaced by FakeExtractor. What the real model decides is an
eval question (ADR 0002), not a test question; these tests pin what the app
does with whatever comes back.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import func, select

from app.commitments.extraction import PROMPT_VERSION, AnthropicExtractor
from app.commitments.schemas import MeetingInput, Segment
from app.commitments.service import store_meeting
from app.db import models
from tests.fakes import candidate


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _extract(client, doc_id):
    return await client.post(f"/api/documents/{doc_id}/extract")


async def test_successful_run_stores_candidates(signed_in_client, db, stored_meeting, fake_extractor):
    fake_extractor.returns([
        candidate(),
        candidate(summary="Find an hour for the volunteer form", quote="I will absolutely do it", strength="soft",
                  due_text="next week", due_on=None),
    ])

    resp = await _extract(signed_in_client, stored_meeting.id)

    assert resp.status_code == 201
    body = resp.json()
    run = body["run"]
    assert run["status"] == "succeeded"
    assert run["model"] == "fake-model"
    assert run["prompt_version"] == PROMPT_VERSION == "v1"
    assert run["input_tokens"] == 1200 and run["output_tokens"] == 150
    assert run["finished_at"] >= run["started_at"]

    items = body["commitments"]
    assert [c["position"] for c in items] == [0, 1]
    assert all(c["status"] == "candidate" for c in items)
    assert [c["quote_found"] for c in items] == [True, False]
    assert items[0]["due_on"] == "2026-10-22"
    assert items[1]["due_on"] is None
    assert all(c["run_id"] == run["id"] for c in items)

    events = (await db.execute(select(models.StatusEvent))).scalars().all()
    assert len(events) == 2
    assert all(e.from_status is None and e.to_status == "candidate" for e in events)


async def test_empty_result_is_a_successful_run(signed_in_client, db, stored_meeting, fake_extractor):
    fake_extractor.returns([])
    resp = await _extract(signed_in_client, stored_meeting.id)
    assert resp.status_code == 201
    assert resp.json()["commitments"] == []
    assert resp.json()["run"]["status"] == "succeeded"


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(lambda f: f.raises(RuntimeError("model unavailable")), id="extractor-raises"),
        pytest.param(lambda f: f.returns([{k: v for k, v in candidate().items() if k != "strength"}]),
                     id="missing-strength"),
        pytest.param(lambda f: f.returns_raw({"commitments": "not a list"}), id="commitments-not-a-list"),
        pytest.param(lambda f: f.returns([candidate(strength="definitely")]), id="unknown-strength"),
        pytest.param(lambda f: f.returns([candidate(summary="")]), id="empty-summary"),
    ],
)
async def test_failed_run_stores_nothing(signed_in_client, db, stored_meeting, fake_extractor, setup):
    setup(fake_extractor)

    resp = await _extract(signed_in_client, stored_meeting.id)

    assert resp.status_code == 502
    run_id = resp.json()["run_id"]
    run = await db.get(models.ExtractionRun, __import__("uuid").UUID(run_id))
    assert run.status == "failed"
    assert run.error
    assert run.finished_at is not None
    assert await _count(db, models.Commitment) == 0
    assert await _count(db, models.StatusEvent) == 0


async def test_one_bad_candidate_fails_the_whole_run(signed_in_client, db, stored_meeting, fake_extractor):
    fake_extractor.returns([candidate(), candidate(quote=None)])
    resp = await _extract(signed_in_client, stored_meeting.id)
    assert resp.status_code == 502
    assert await _count(db, models.Commitment) == 0


async def test_missing_api_key_is_503_and_creates_no_run(signed_in_client, db, stored_meeting):
    # No fake installed and ANTHROPIC_API_KEY unset (conftest removes it).
    resp = await _extract(signed_in_client, stored_meeting.id)
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]
    assert await _count(db, models.ExtractionRun) == 0


async def test_extracting_twice_keeps_both_runs(signed_in_client, db, stored_meeting, fake_extractor):
    fake_extractor.returns([candidate(), candidate(summary="Second thing")])
    first = (await _extract(signed_in_client, stored_meeting.id)).json()
    second = (await _extract(signed_in_client, stored_meeting.id)).json()

    assert first["run"]["id"] != second["run"]["id"]
    assert await _count(db, models.ExtractionRun) == 2
    assert await _count(db, models.Commitment) == 4
    assert {c["run_id"] for c in second["commitments"]} == {second["run"]["id"]}


async def test_prompt_carries_local_date_and_my_speaker(signed_in_client, stored_meeting, fake_extractor):
    await _extract(signed_in_client, stored_meeting.id)
    call = fake_extractor.calls[0]
    assert "2026-10-20" in call["user"]
    assert "Frank E." in call["user"]
    assert "frank@example.com" in call["user"]
    assert "[00:00:11] Frank E.: Got it." in call["user"]
    assert call["system"].strip()  # the versioned prompt file, not empty


async def test_run_records_who_was_identified(signed_in_client, stored_meeting, fake_extractor):
    body = (await _extract(signed_in_client, stored_meeting.id)).json()
    assert body["run"]["my_speaker"] == "Frank E."


async def test_extract_requires_session(client, stored_meeting, fake_extractor):
    client.cookies.clear()
    resp = await client.post(f"/api/documents/{stored_meeting.id}/extract")
    assert resp.status_code == 401
    assert fake_extractor.calls == []


async def test_anthropic_extractor_constructs_offline_and_cannot_escape():
    extractor = AnthropicExtractor(api_key="sk-test-not-real", model="claude-sonnet-5-5", timeout=5, max_retries=0)
    assert extractor.model == "claude-sonnet-5-5"
    with pytest.raises(Exception) as excinfo:
        await extractor.extract(system="s", user="u")
    # The network guard in conftest is what stopped it.
    chain, exc = [], excinfo.value
    while exc is not None:
        chain.append(str(exc))
        exc = exc.__cause__ or exc.__context__
    assert any("network call attempted in tests" in m for m in chain)


SENTINEL = "ZQX-SENTINEL-77"


async def test_transcript_text_never_reaches_error_or_logs(signed_in_client, db, current_user, fake_extractor, caplog):
    meeting = MeetingInput(
        external_id="sentinel-1",
        title="Sentinel call",
        occurred_at=__import__("datetime").datetime(2026, 10, 20, 18, 0, tzinfo=__import__("datetime").timezone.utc),
        recorded_by_name="Frank Example",
        recorded_by_email="frank@example.com",
        segments=[Segment(speaker="Frank Example", email=None, timestamp="00:00:01",
                          text=f"The secret code is {SENTINEL}.")],
    )
    doc, _ = await store_meeting(db, current_user, meeting)
    # A failure whose message carries the transcript, first line included.
    fake_extractor.raises(RuntimeError(f"bad request for: {SENTINEL}\nmore {SENTINEL}"))

    with caplog.at_level(logging.DEBUG):
        resp = await _extract(signed_in_client, doc.id)

    assert resp.status_code == 502
    assert SENTINEL not in resp.text
    run = (await db.execute(select(models.ExtractionRun))).scalar_one()
    assert SENTINEL not in (run.error or "")
    assert SENTINEL not in caplog.text
