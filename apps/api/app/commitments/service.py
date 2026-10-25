"""Storing meetings, running extraction, and reviewing commitments.

Routers and (from Task B) the sync job call these; nothing else writes the
Phase 1 tables.

Two rules hold everywhere here:
- An extraction run is all or nothing. The run row is committed before the
  model is called, so a crash still leaves a record; candidates are only
  written, together with the run's success, in one later commit.
- Transcript text and model output never reach a log line or an error
  string. Errors are described by `describe_error`, which reports the
  exception class and fields known to be safe, never the message.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.commitments import transcript as tx
from app.commitments.enums import CommitmentStatus, RunStatus
from app.commitments.extraction import (
    PROMPT_VERSION,
    ExtractionContext,
    Extractor,
    build_user_message,
    system_prompt,
)
from app.commitments.schemas import CommitmentPatch, ExtractionOutput, MeetingInput, Segment
from app.db.models import Commitment, ExtractionRun, SourceDocument, StatusEvent, User

logger = logging.getLogger(__name__)

S = CommitmentStatus
TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (S.CANDIDATE, S.ACCEPTED),
        (S.CANDIDATE, S.REJECTED),
        (S.ACCEPTED, S.DONE),
        (S.ACCEPTED, S.DROPPED),
        (S.REJECTED, S.CANDIDATE),
        (S.DONE, S.ACCEPTED),
        (S.DROPPED, S.ACCEPTED),
    }
)
EDITABLE_STATUSES = frozenset({S.CANDIDATE, S.ACCEPTED})


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class ExtractionFailed(Exception):
    def __init__(self, run: ExtractionRun):
        super().__init__("extraction failed")
        self.run = run


def now() -> datetime:
    return datetime.now(timezone.utc)


def describe_error(exc: BaseException) -> str:
    """A short, safe description of a failure. Never includes the message.

    Exception messages from the model SDK or from validation can quote the
    request or the model's output, and both contain transcript text.
    """
    name = type(exc).__name__
    if isinstance(exc, ValidationError):
        locs = sorted({".".join(str(p) for p in e["loc"]) or "(root)" for e in exc.errors()})
        return f"{name}: invalid model output at {', '.join(locs)}"[:500]
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return f"{name}: HTTP {status_code}"
    return name


# --- Meetings --------------------------------------------------------------


async def find_document(db: AsyncSession, user: User | uuid.UUID, kind: str, external_id: str) -> SourceDocument | None:
    user_id = user if isinstance(user, uuid.UUID) else user.id
    return (
        await db.execute(
            select(SourceDocument).where(
                SourceDocument.user_id == user_id,
                SourceDocument.kind == kind,
                SourceDocument.external_id == external_id,
            )
        )
    ).scalar_one_or_none()


async def store_meeting(db: AsyncSession, user: User, meeting: MeetingInput) -> tuple[SourceDocument, bool]:
    """Store a meeting once. Returns (document, created).

    A meeting already stored, including one that was removed (a tombstone),
    is returned as is with created=False.
    """
    user_id = user.id  # read now: a rollback below would expire `user`
    existing = await find_document(db, user_id, meeting.kind, meeting.external_id)
    if existing is not None:
        return existing, False

    raw_text = tx.render(meeting.segments)
    doc = SourceDocument(
        user_id=user_id,
        kind=meeting.kind,
        external_id=meeting.external_id,
        title=meeting.title[:300],
        occurred_at=meeting.occurred_at,
        occurred_on=tx.local_date(meeting.occurred_at, settings.local_timezone()),
        source_url=(meeting.source_url or None) and meeting.source_url[:500],
        recorded_by_name=meeting.recorded_by_name,
        recorded_by_email=meeting.recorded_by_email,
        raw_text=raw_text,
        segments=[s.model_dump() for s in meeting.segments],
        speakers=tx.speakers(meeting.segments),
        my_speaker=tx.identify_me(meeting.segments, name=meeting.recorded_by_name, email=meeting.recorded_by_email),
        char_count=len(raw_text),
        vendor_action_items=meeting.vendor_action_items,
    )
    db.add(doc)
    try:
        await db.commit()
    except IntegrityError:
        # Another store of the same meeting won the race; use its row.
        await db.rollback()
        existing = await find_document(db, user_id, meeting.kind, meeting.external_id)
        if existing is None:
            raise
        return existing, False
    await db.refresh(doc)
    return doc, True


async def get_live_document(db: AsyncSession, user: User, document_id: uuid.UUID) -> SourceDocument:
    doc = await db.get(SourceDocument, document_id)
    if doc is None or doc.user_id != user.id or doc.removed_at is not None:
        raise NotFound
    return doc


async def remove_document(db: AsyncSession, user: User, document_id: uuid.UUID) -> None:
    """Delete a meeting's runs, commitments, and history; keep a tombstone."""
    doc = await get_live_document(db, user, document_id)
    commitment_ids = select(Commitment.id).where(Commitment.document_id == doc.id)
    await db.execute(delete(StatusEvent).where(StatusEvent.commitment_id.in_(commitment_ids)))
    await db.execute(delete(Commitment).where(Commitment.document_id == doc.id))
    await db.execute(delete(ExtractionRun).where(ExtractionRun.document_id == doc.id))
    doc.raw_text = ""
    doc.segments = []
    doc.speakers = []
    doc.char_count = 0
    doc.vendor_action_items = None
    doc.removed_at = now()
    await db.commit()


async def status_counts(db: AsyncSession, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    counts: dict[uuid.UUID, dict[str, int]] = {d: {} for d in document_ids}
    if not document_ids:
        return counts
    rows = await db.execute(
        select(Commitment.document_id, Commitment.status, func.count())
        .where(Commitment.document_id.in_(document_ids))
        .group_by(Commitment.document_id, Commitment.status)
    )
    for doc_id, status, n in rows:
        counts[doc_id][status] = n
    return counts


# --- Extraction ------------------------------------------------------------


class _RemovedDuringRun(Exception):
    pass


async def _is_live(db: AsyncSession, document_id: uuid.UUID) -> bool:
    row = (
        await db.execute(select(SourceDocument.removed_at).where(SourceDocument.id == document_id))
    ).first()
    return row is not None and row[0] is None


def _segments(doc: SourceDocument) -> list[Segment]:
    return [Segment.model_validate(s) for s in doc.segments]


async def run_extraction(db: AsyncSession, doc: SourceDocument, extractor: Extractor) -> tuple[ExtractionRun, list[Commitment]]:
    """One model call against one document.

    Raises NotFound if the document is removed (before or during the call),
    and ExtractionFailed for every other failure.
    """
    if doc.removed_at is not None:
        raise NotFound
    doc_id = doc.id
    run = ExtractionRun(
        document_id=doc.id,
        status=RunStatus.RUNNING,
        model=extractor.model,
        prompt_version=PROMPT_VERSION,
        my_speaker=doc.my_speaker,
        started_at=now(),
    )
    db.add(run)
    await db.commit()
    run_id = run.id

    ctx = ExtractionContext(
        title=doc.title,
        meeting_date=doc.occurred_on,
        my_speaker=doc.my_speaker,
        my_name=doc.recorded_by_name,
        my_email=doc.recorded_by_email,
    )
    segments = _segments(doc)
    try:
        result = await extractor.extract(
            system=system_prompt(PROMPT_VERSION),
            user=build_user_message(doc.raw_text, ctx),
        )
        output = ExtractionOutput.model_validate(result.raw)
        if not await _is_live(db, doc_id):
            raise _RemovedDuringRun

        created: list[Commitment] = []
        stamp = now()
        for position, cand in enumerate(output.commitments):
            row = Commitment(
                id=uuid.uuid4(),
                document_id=doc.id,
                run_id=run_id,
                status=S.CANDIDATE,
                summary=cand.summary,
                counterparty=cand.counterparty,
                speaker=cand.speaker,
                quote=cand.quote,
                quote_found=tx.quote_found(cand.quote, segments),
                strength=cand.strength,
                due_text=cand.due_text,
                due_on=cand.due_on,
                details=cand.details,
                position=position,
                created_at=stamp,
                updated_at=stamp,
            )
            created.append(row)
            db.add(row)
        await db.flush()
        for row in created:
            db.add(StatusEvent(commitment_id=row.id, from_status=None, to_status=S.CANDIDATE, created_at=stamp))

        run.status = RunStatus.SUCCEEDED
        run.model = result.model or extractor.model
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.raw_output = result.raw if isinstance(result.raw, (dict, list)) else None
        run.finished_at = max(now(), run.started_at)
        await db.commit()
        return run, created
    except Exception as exc:  # noqa: BLE001  (every failure becomes a failed run)
        await db.rollback()
        failed = await db.get(ExtractionRun, run_id)
        if failed is None or not await _is_live(db, doc_id):
            # The meeting was removed while the model was working; its runs
            # went with it. Nothing to record.
            raise NotFound from None
        error = describe_error(exc)
        failed.status = RunStatus.FAILED
        failed.error = error
        failed.finished_at = max(now(), failed.started_at)
        await db.commit()
        logger.warning("extraction run %s failed: %s", run_id, error)
        raise ExtractionFailed(failed) from None


# --- Review ----------------------------------------------------------------


async def get_commitment(db: AsyncSession, user: User, commitment_id: uuid.UUID) -> Commitment:
    row = await db.get(Commitment, commitment_id)
    if row is None:
        raise NotFound
    doc = await db.get(SourceDocument, row.document_id)
    if doc is None or doc.user_id != user.id or doc.removed_at is not None:
        raise NotFound
    return row


async def change_status(db: AsyncSession, user: User, commitment_id: uuid.UUID, to: str, note: str | None) -> Commitment:
    row = await get_commitment(db, user, commitment_id)
    if (row.status, to) not in TRANSITIONS:
        raise Conflict(f"cannot move a commitment from {row.status} to {to}")
    stamp = now()
    db.add(StatusEvent(commitment_id=row.id, from_status=row.status, to_status=to, note=note, created_at=stamp))
    row.status = to
    row.updated_at = stamp
    await db.commit()
    return row


async def edit_commitment(db: AsyncSession, user: User, commitment_id: uuid.UUID, patch: CommitmentPatch) -> Commitment:
    row = await get_commitment(db, user, commitment_id)
    if row.status not in EDITABLE_STATUSES:
        raise Conflict(f"a {row.status} commitment cannot be edited; restore it first")
    changes: dict[str, Any] = patch.model_dump(include=patch.model_fields_set)
    for field, value in changes.items():
        setattr(row, field, value)
    if changes:
        row.updated_at = now()
    await db.commit()
    return row
