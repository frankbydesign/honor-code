"""The Fathom sync: pull new meetings, store them, extract commitments.

One sync at a time, guarded by a process-wide lock. A sync writes one
sync_runs row and then, in order:

1. Lists Fathom meetings created since the window start.
2. For each meeting not already stored (oldest first), fetches the
   transcript and stores it. An empty transcript means Fathom is still
   processing, and a failed fetch means it would not serve this one; both
   count as pending and are tried next time, and the sync moves on.
3. Extracts every live meeting that has no successful extraction and
   fewer than MAX_EXTRACTION_FAILURES failed ones. Failures are counted
   but do not fail the sync.

The window: the first sync reaches FATHOM_BACKFILL_DAYS back. Later syncs
start OVERLAP before the start of the last successful sync, which catches
meetings Fathom finished processing late; storing is deduplicated, so the
overlap is free. If that sync left meetings pending, the window reaches
back to its own start instead (never further than the backfill), so a
meeting whose transcript arrives days later is not lost.

Each meeting and each extraction gets its own database session, so a
failure in one cannot leave another's objects in a bad state.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import settings
from app.auth import config as auth_config
from app.commitments import service as commitments
from app.commitments.enums import DocumentKind, RunStatus, SyncTrigger
from app.commitments.extraction import Extractor
from app.db.models import ExtractionRun, SourceDocument, SyncRun, User
from app.db.session import SessionLocal
from app.sources.fathom import MeetingSource, SourceError, to_meeting_input

logger = logging.getLogger(__name__)

SOURCE = "fathom"
OVERLAP = timedelta(hours=48)
MAX_EXTRACTION_FAILURES = 3
SCHEDULER_TASK_NAME = "honor-code-sync-scheduler"
_BACKGROUND_TASK_NAME = "honor-code-sync"

_lock = asyncio.Lock()
_background: asyncio.Task | None = None


class SyncInProgress(Exception):
    pass


class NoUser(Exception):
    pass


def is_running() -> bool:
    return _lock.locked()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def describe_sync_error(exc: BaseException) -> str:
    if isinstance(exc, SourceError):
        return f"SourceError: {exc}"[:500]
    if isinstance(exc, NoUser):
        return "NoUser: sign in to the app once so synced meetings have an owner"
    return commitments.describe_error(exc)


async def _owner_id(db: AsyncSession) -> uuid.UUID:
    allowed = sorted(auth_config.ALLOWED_EMAILS)
    user_id = (
        await db.execute(
            select(User.id).where(func.lower(User.email).in_(allowed)).order_by(User.created_at).limit(1)
        )
    ).scalar_one_or_none()
    if user_id is None:
        raise NoUser
    return user_id


async def compute_window_start(db: AsyncSession, now: datetime) -> datetime:
    backfill_start = now - timedelta(days=settings.fathom_backfill_days())
    last = (
        await db.execute(
            select(SyncRun)
            .where(SyncRun.source == SOURCE, SyncRun.status == RunStatus.SUCCEEDED)
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None:
        return backfill_start
    start = last.started_at - OVERLAP
    if last.meetings_pending > 0:
        start = min(start, max(last.window_start, backfill_start))
    # A sync recorded while the clock ran fast must not push the window
    # past meetings that really happened.
    return min(start, now - OVERLAP)


async def _create_run(factory: async_sessionmaker[AsyncSession], trigger: str, now: datetime) -> uuid.UUID:
    async with factory() as db:
        run = SyncRun(
            source=SOURCE,
            trigger=trigger,
            status=RunStatus.RUNNING,
            window_start=await compute_window_start(db, now),
            started_at=now,
        )
        db.add(run)
        await db.commit()
        return run.id


async def _store_new_meetings(factory, source: MeetingSource, user_id: uuid.UUID, window_start: datetime):
    """Returns (seen, new, pending, transcript_failures, first_failure).

    A failed transcript fetch counts as pending and the sync moves on: one
    recording Fathom will not serve (deleted, no access) must not stop the
    meetings after it. Pending meetings keep the next window open for them.
    A failure to list meetings is raised to the caller.
    """
    meetings = await source.list_meetings(created_after=window_start)
    seen, new, pending, failures = len(meetings), 0, 0, 0
    first_failure: BaseException | None = None
    for meeting in sorted(meetings, key=lambda m: (m.created_at, m.recording_id)):
        external_id = str(meeting.recording_id)
        async with factory() as db:
            if await commitments.find_document(db, user_id, DocumentKind.FATHOM_MEETING, external_id):
                continue
        try:
            items = await source.get_transcript(meeting.recording_id)
        except Exception as exc:  # noqa: BLE001
            pending += 1
            failures += 1
            first_failure = first_failure or exc
            continue
        if not items:
            pending += 1
            continue
        async with factory() as db:
            _, created = await commitments.store_meeting(db, user_id, to_meeting_input(meeting, items))
        new += int(created)
    return seen, new, pending, failures, first_failure


async def _extract_outstanding(factory, user_id: uuid.UUID, extractor: Extractor) -> tuple[int, int]:
    async with factory() as db:
        succeeded = (
            select(ExtractionRun.document_id)
            .where(ExtractionRun.status == RunStatus.SUCCEEDED)
            .scalar_subquery()
        )
        failures = (
            select(func.count())
            .select_from(ExtractionRun)
            .where(ExtractionRun.document_id == SourceDocument.id, ExtractionRun.status == RunStatus.FAILED)
            .correlate(SourceDocument)
            .scalar_subquery()
        )
        doc_ids = (
            await db.execute(
                select(SourceDocument.id)
                .where(
                    SourceDocument.user_id == user_id,
                    SourceDocument.removed_at.is_(None),
                    SourceDocument.id.not_in(succeeded),
                    failures < MAX_EXTRACTION_FAILURES,
                )
                .order_by(SourceDocument.occurred_at)
            )
        ).scalars().all()

    ok = failed = 0
    for doc_id in doc_ids:
        async with factory() as db:
            doc = await db.get(SourceDocument, doc_id)
            if doc is None:
                continue
            try:
                await commitments.run_extraction(db, doc, extractor)
                ok += 1
            except commitments.NotFound:
                continue  # removed while we were working
            except commitments.ExtractionFailed:
                failed += 1
    return ok, failed


async def _finish(factory, run_id: uuid.UUID, *, status: str, error: str | None, counts: dict[str, int]) -> SyncRun:
    async with factory() as db:
        run = await db.get(SyncRun, run_id)
        for field, value in counts.items():
            setattr(run, field, value)
        run.status = status
        run.error = error[:500] if error else None
        run.finished_at = max(_utcnow(), run.started_at)
        await db.commit()
        return run


async def _execute(
    factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID, source: MeetingSource, extractor: Extractor
) -> SyncRun:
    counts = dict(meetings_seen=0, meetings_new=0, meetings_pending=0, extractions_ok=0, extractions_failed=0)
    fatal: BaseException | None = None
    note: str | None = None
    try:
        async with factory() as db:
            window_start = (await db.get(SyncRun, run_id)).window_start
            user_id = await _owner_id(db)
        seen, new, pending, failures, first_failure = await _store_new_meetings(
            factory, source, user_id, window_start
        )
        counts.update(meetings_seen=seen, meetings_new=new, meetings_pending=pending)
        if failures:
            note = (
                f"{failures} transcript{'s' if failures != 1 else ''} could not be fetched and will be "
                f"retried; first: {describe_sync_error(first_failure)}"
            )
        ok, failed = await _extract_outstanding(factory, user_id, extractor)
        counts.update(extractions_ok=ok, extractions_failed=failed)
    except asyncio.CancelledError:
        # App shutdown (or a cancelled task): record it, then let it go.
        await _finish(factory, run_id, status=RunStatus.FAILED, error="cancelled", counts=counts)
        raise
    except Exception as exc:  # noqa: BLE001  (every failure ends up on the run row)
        fatal = exc

    if fatal is not None:
        run = await _finish(factory, run_id, status=RunStatus.FAILED, error=describe_sync_error(fatal), counts=counts)
        logger.warning("sync %s failed: %s", run_id, run.error)
    else:
        run = await _finish(factory, run_id, status=RunStatus.SUCCEEDED, error=note, counts=counts)
        logger.info(
            "sync %s: %d new meetings, %d pending, %d extracted, %d extraction failures",
            run_id, run.meetings_new, run.meetings_pending, run.extractions_ok, run.extractions_failed,
        )
    return run


async def sweep_interrupted(factory: async_sessionmaker[AsyncSession] = SessionLocal) -> int:
    """Close sync and extraction runs left 'running' by a previous process."""
    from sqlalchemy import update

    stamp = _utcnow()
    async with factory() as db:
        total = 0
        for model in (SyncRun, ExtractionRun):
            result = await db.execute(
                update(model)
                .where(model.status == RunStatus.RUNNING)
                .values(status=RunStatus.FAILED, error="interrupted", finished_at=stamp)
            )
            total += result.rowcount or 0
        await db.commit()
    return total


async def cancel_background() -> None:
    """Cancel a Sync now still running at shutdown, and wait for it to record that."""
    task = _background
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _acquire() -> None:
    if _lock.locked():
        raise SyncInProgress
    await _lock.acquire()


async def run_sync(
    trigger: str,
    *,
    source: MeetingSource,
    extractor: Extractor,
    now: datetime | None = None,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> SyncRun:
    """Run one sync to completion. Raises SyncInProgress if one is running."""
    await _acquire()
    try:
        run_id = await _create_run(session_factory, SyncTrigger(trigger), now or _utcnow())
        return await _execute(session_factory, run_id, source, extractor)
    finally:
        _lock.release()


async def start_sync(
    trigger: str,
    *,
    source: MeetingSource,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> SyncRun:
    """Create the run row and continue the sync in the background."""
    global _background
    await _acquire()
    try:
        run_id = await _create_run(session_factory, SyncTrigger(trigger), _utcnow())
        async with session_factory() as db:
            run = await db.get(SyncRun, run_id)
    except BaseException:
        _lock.release()
        raise

    async def body() -> None:
        try:
            await _execute(session_factory, run_id, source, extractor)
        except Exception as exc:  # noqa: BLE001
            logger.warning("background sync %s crashed: %s", run_id, type(exc).__name__)
        finally:
            _lock.release()

    _background = asyncio.create_task(body(), name=_BACKGROUND_TASK_NAME)
    return run


async def wait_until_idle() -> None:
    """Wait for a background sync started by start_sync, if any."""
    task = _background
    if task is not None and not task.done():
        await asyncio.gather(task, return_exceptions=True)


def default_dependencies() -> tuple[MeetingSource | None, Extractor | None]:
    from app.commitments.router import get_extractor
    from app.sources.fathom import FathomClient

    key = settings.fathom_api_key()
    return (FathomClient(api_key=key) if key else None), get_extractor()


async def run_scheduled_sync(trigger: str) -> None:
    """What the scheduler calls. Quietly skips when not configured."""
    source, extractor = default_dependencies()
    if source is None or extractor is None:
        return
    await run_sync(trigger, source=source, extractor=extractor)
