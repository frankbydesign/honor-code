"""The Fathom sync: what it stores, what it skips, and how it fails.

Fathom and the model are both fakes. `now` is passed in, so the window
arithmetic is exact.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.commitments import service as commitments_service
from app.db import models
from app.sources.fathom import SourceError
from app.sync.service import SyncInProgress, run_sync
from tests.fakes import candidate, fathom_fixture_source

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


async def _count(db, model, *where) -> int:
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    return (await db.execute(q)).scalar_one()


async def _docs(db):
    return (await db.execute(select(models.SourceDocument).order_by(models.SourceDocument.external_id))).scalars().all()


@pytest.fixture
def source():
    return fathom_fixture_source()


async def test_first_sync_reaches_back_fourteen_days_and_stores_everything(current_user, db, source, fake_extractor):
    fake_extractor.returns([candidate()])

    run = await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)

    assert run.status == "succeeded"
    assert run.trigger == "startup"
    assert run.window_start == NOW - timedelta(days=14)
    assert source.list_calls == [NOW - timedelta(days=14)]
    assert (run.meetings_seen, run.meetings_new, run.meetings_pending) == (3, 3, 0)
    assert (run.extractions_ok, run.extractions_failed) == (3, 0)
    assert run.finished_at is not None
    docs = await _docs(db)
    assert [d.external_id for d in docs] == ["900101", "900102", "900103"]
    assert all(d.user_id == current_user.id for d in docs)
    assert await _count(db, models.Commitment) == 3


async def test_backfill_window_follows_setting(current_user, source, fake_extractor, monkeypatch):
    monkeypatch.setenv("FATHOM_BACKFILL_DAYS", "3")
    run = await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    assert run.window_start == NOW - timedelta(days=3)


async def test_later_sync_overlaps_48_hours_and_skips_stored_meetings(current_user, db, source, fake_extractor):
    first = await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    later = NOW + timedelta(hours=1)

    second = await run_sync("interval", source=source, extractor=fake_extractor, now=later)

    assert second.window_start == first.started_at - timedelta(hours=48)
    assert second.meetings_new == 0
    assert second.extractions_ok == 0  # already extracted
    assert sorted(source.transcript_calls) == [900101, 900102, 900103]  # fetched once each
    assert await _count(db, models.SourceDocument) == 3
    assert await _count(db, models.ExtractionRun) == 3


async def test_window_follows_last_success_not_last_failure(current_user, source, fake_extractor):
    await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    source.list_error = SourceError("Fathom returned HTTP 500")
    await run_sync("interval", source=source, extractor=fake_extractor, now=NOW + timedelta(days=1))
    source.list_error = None

    third = await run_sync("interval", source=source, extractor=fake_extractor, now=NOW + timedelta(days=2))

    assert third.window_start == NOW - timedelta(hours=48)


async def test_empty_transcript_is_pending_and_picked_up_later(current_user, db, source, fake_extractor):
    held = source.transcripts.pop(900102)

    first = await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    assert first.meetings_pending == 1
    assert [d.external_id for d in await _docs(db)] == ["900101", "900103"]

    # Fathom finishes processing. 900102 was created more than 48 hours
    # before this sync, so only the pending carry-over keeps it in range.
    source.transcripts[900102] = held
    second = await run_sync("interval", source=source, extractor=fake_extractor, now=NOW + timedelta(hours=1))

    assert second.meetings_new == 1
    assert second.meetings_pending == 0
    assert [d.external_id for d in await _docs(db)] == ["900101", "900102", "900103"]


async def test_removed_meeting_is_not_reimported(current_user, db, source, fake_extractor):
    await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    doc = next(d for d in await _docs(db) if d.external_id == "900101")
    await commitments_service.remove_document(db, current_user, doc.id)
    calls_before = list(source.transcript_calls)

    run = await run_sync("manual", source=source, extractor=fake_extractor, now=NOW + timedelta(hours=1))

    assert run.meetings_new == 0
    assert source.transcript_calls == calls_before
    db.expunge_all()
    again = await db.get(models.SourceDocument, doc.id)
    assert again.removed_at is not None and again.raw_text == ""
    assert await _count(db, models.ExtractionRun, models.ExtractionRun.document_id == doc.id) == 0


async def test_extraction_failure_is_counted_retried_and_capped(current_user, db, source, fake_extractor):
    fake_extractor.raises(RuntimeError("model down"))

    results = []
    for hour in range(4):
        run = await run_sync("interval", source=source, extractor=fake_extractor, now=NOW + timedelta(hours=hour))
        results.append((run.status, run.extractions_ok, run.extractions_failed))

    assert results == [
        ("succeeded", 0, 3),
        ("succeeded", 0, 3),
        ("succeeded", 0, 3),
        ("succeeded", 0, 0),  # three failures each: no more automatic retries
    ]
    assert await _count(db, models.ExtractionRun) == 9
    assert await _count(db, models.Commitment) == 0


async def test_retry_after_failure_succeeds(current_user, db, source, fake_extractor):
    fake_extractor.raises(RuntimeError("model down"))
    await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    fake_extractor.returns([candidate()])

    run = await run_sync("interval", source=source, extractor=fake_extractor, now=NOW + timedelta(hours=1))

    assert run.extractions_ok == 3
    assert await _count(db, models.Commitment) == 3


async def test_list_failure_fails_the_run_with_a_safe_reason(current_user, db, source, fake_extractor):
    source.list_error = SourceError("Fathom returned HTTP 401 for /meetings")

    run = await run_sync("manual", source=source, extractor=fake_extractor, now=NOW)

    assert run.status == "failed"
    assert "401" in run.error
    assert run.finished_at is not None
    assert await _count(db, models.SourceDocument) == 0


async def test_unexpected_error_fails_the_run_without_its_message(current_user, source, fake_extractor):
    source.list_error = ValueError("secret transcript words")
    run = await run_sync("manual", source=source, extractor=fake_extractor, now=NOW)
    assert run.status == "failed"
    assert "secret transcript words" not in run.error
    assert "ValueError" in run.error


async def test_one_failing_transcript_does_not_block_the_others(current_user, db, source, fake_extractor):
    # Review finding: a recording whose transcript always fails (deleted,
    # no access) must not stop newer meetings from arriving.
    source.transcript_errors[900101] = SourceError("Fathom returned HTTP 404 for /recordings/900101/transcript")
    fake_extractor.returns([candidate()])

    run = await run_sync("manual", source=source, extractor=fake_extractor, now=NOW)

    assert run.status == "succeeded"
    assert [d.external_id for d in await _docs(db)] == ["900102", "900103"]
    assert run.meetings_new == 2
    assert run.meetings_pending == 1  # tried again next time
    assert "404" in run.error  # the reason is still visible
    assert run.extractions_ok == 2


async def test_failing_transcript_is_retried_and_window_keeps_moving(current_user, db, source, fake_extractor):
    source.transcript_errors[900101] = SourceError("Fathom returned HTTP 500 for /recordings/900101/transcript")
    first = await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    del source.transcript_errors[900101]

    later = NOW + timedelta(hours=6)
    second = await run_sync("interval", source=source, extractor=fake_extractor, now=later)

    assert second.window_start <= datetime(2026, 10, 20, 17, 45, tzinfo=timezone.utc)  # still covers 900101
    assert second.window_start > first.window_start - timedelta(seconds=1) or second.window_start == first.window_start
    assert [d.external_id for d in await _docs(db)] == ["900101", "900102", "900103"]


async def test_window_never_starts_in_the_future_after_a_clock_jump(current_user, source, fake_extractor):
    # A sync that ran while the laptop clock was days fast must not push
    # later windows past real meetings.
    await run_sync("startup", source=source, extractor=fake_extractor, now=NOW + timedelta(days=10))
    run = await run_sync("interval", source=source, extractor=fake_extractor, now=NOW)
    assert run.window_start <= NOW - timedelta(hours=48)


async def test_cancelled_sync_is_recorded_and_releases_the_lock(current_user, db, source, fake_extractor):
    source.gate = asyncio.Event()
    task = asyncio.create_task(run_sync("startup", source=source, extractor=fake_extractor, now=NOW))
    for _ in range(100):
        if source.list_calls:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    run = (await db.execute(select(models.SyncRun))).scalar_one()
    assert run.status == "failed"
    assert run.error == "cancelled"
    assert run.finished_at is not None
    # The next sync can start.
    source.gate = None
    again = await run_sync("manual", source=source, extractor=fake_extractor, now=NOW + timedelta(minutes=5))
    assert again.status == "succeeded"


async def test_meetings_are_processed_oldest_first(current_user, source, fake_extractor):
    source.meetings.reverse()
    await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    assert source.transcript_calls == [900101, 900102, 900103]


async def test_sync_without_a_signed_in_user_fails_readably(db, source, fake_extractor):
    run = await run_sync("startup", source=source, extractor=fake_extractor, now=NOW)
    assert run.status == "failed"
    assert "sign in" in run.error.lower()
    assert source.list_calls == []


async def test_two_syncs_cannot_overlap(current_user, source, fake_extractor):
    source.gate = asyncio.Event()
    first = asyncio.create_task(run_sync("startup", source=source, extractor=fake_extractor, now=NOW))
    for _ in range(100):
        if source.list_calls:
            break
        await asyncio.sleep(0.01)
    assert source.list_calls, "first sync never started"

    with pytest.raises(SyncInProgress):
        await run_sync("manual", source=source, extractor=fake_extractor, now=NOW)

    source.gate.set()
    run = await asyncio.wait_for(first, timeout=5)
    assert run.status == "succeeded"
    assert len(source.list_calls) == 1


async def test_vendor_action_items_are_kept(current_user, db, fake_extractor):
    from app.sources.fathom import FathomMeeting
    from tests.conftest import load_fixture
    from tests.fakes import FakeMeetingSource

    meeting = FathomMeeting.model_validate(load_fixture("fathom/meeting_basic.json"))
    src = FakeMeetingSource([meeting], {meeting.recording_id: meeting.transcript})
    await run_sync("startup", source=src, extractor=fake_extractor, now=NOW)

    (doc,) = await _docs(db)
    assert doc.vendor_action_items[0]["description"] == "Send revised budget to Alice"
