"""HTTP API for meetings, extraction, and review. Mounted under /api."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.auth.deps import get_current_user
from app.commitments import service
from app.commitments.enums import CommitmentStatus
from app.commitments.extraction import AnthropicExtractor, Extractor
from app.commitments.schemas import (
    CommitmentOut,
    CommitmentPatch,
    DocumentDetail,
    DocumentRef,
    DocumentSummary,
    EventOut,
    ExtractResponse,
    RunOut,
    StatusChange,
    StatusCounts,
)
from app.db.models import Commitment, ExtractionRun, SourceDocument, StatusEvent, User
from app.db.session import get_session

router = APIRouter(tags=["commitments"])


def get_extractor() -> Extractor | None:
    """The real extractor when ANTHROPIC_API_KEY is set, else None (503)."""
    key = settings.anthropic_api_key()
    if key is None:
        return None
    return AnthropicExtractor(
        api_key=key,
        model=settings.extraction_model(),
        timeout=settings.extraction_timeout_seconds(),
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def _summary(doc: SourceDocument, counts: dict[str, int]) -> dict:
    return {
        "id": doc.id,
        "kind": doc.kind,
        "title": doc.title,
        "occurred_at": doc.occurred_at,
        "occurred_on": doc.occurred_on,
        "source_url": doc.source_url,
        "char_count": doc.char_count,
        "counts": StatusCounts(**counts),
    }


def _commitment_out(row: Commitment, doc: SourceDocument | None = None) -> CommitmentOut:
    out = CommitmentOut.model_validate(row)
    if doc is not None:
        out.document = DocumentRef(id=doc.id, title=doc.title, occurred_on=doc.occurred_on)
    return out


# --- Documents -------------------------------------------------------------


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    docs = (
        await db.execute(
            select(SourceDocument)
            .where(SourceDocument.user_id == user.id, SourceDocument.removed_at.is_(None))
            .order_by(SourceDocument.occurred_at.desc())
        )
    ).scalars().all()
    counts = await service.status_counts(db, [d.id for d in docs])
    return [_summary(d, counts[d.id]) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
):
    try:
        doc = await service.get_live_document(db, user, document_id)
    except service.NotFound:
        raise _not_found() from None
    runs = (
        await db.execute(
            select(ExtractionRun).where(ExtractionRun.document_id == doc.id).order_by(ExtractionRun.started_at.desc())
        )
    ).scalars().all()
    commitments = (
        await db.execute(
            select(Commitment)
            .where(Commitment.document_id == doc.id)
            .order_by(Commitment.created_at.desc(), Commitment.position)
        )
    ).scalars().all()
    counts = (await service.status_counts(db, [doc.id]))[doc.id]
    return {
        **_summary(doc, counts),
        "raw_text": doc.raw_text,
        "speakers": doc.speakers,
        "my_speaker": doc.my_speaker,
        "recorded_by_name": doc.recorded_by_name,
        "recorded_by_email": doc.recorded_by_email,
        "vendor_action_items": doc.vendor_action_items,
        "runs": [RunOut.model_validate(r) for r in runs],
        "commitments": [_commitment_out(c) for c in commitments],
    }


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    document_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
):
    try:
        await service.remove_document(db, user, document_id)
    except service.NotFound:
        raise _not_found() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/documents/{document_id}/extract", status_code=status.HTTP_201_CREATED, response_model=ExtractResponse)
async def extract_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    extractor: Extractor | None = Depends(get_extractor),
):
    try:
        doc = await service.get_live_document(db, user, document_id)
    except service.NotFound:
        raise _not_found() from None
    if extractor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="extraction is not configured: set ANTHROPIC_API_KEY in apps/api/.env",
        )
    try:
        run, created = await service.run_extraction(db, doc, extractor)
    except service.ExtractionFailed as failed:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": f"extraction failed ({failed.run.error})", "run_id": str(failed.run.id)},
        )
    return {"run": RunOut.model_validate(run), "commitments": [_commitment_out(c) for c in created]}


# --- Commitments -----------------------------------------------------------


@router.get("/commitments", response_model=list[CommitmentOut])
async def list_commitments(
    status_filter: CommitmentStatus | None = Query(default=None, alias="status"),
    document_id: uuid.UUID | None = None,
    counterparty: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    query = (
        select(Commitment, SourceDocument)
        .join(SourceDocument, SourceDocument.id == Commitment.document_id)
        .where(SourceDocument.user_id == user.id, SourceDocument.removed_at.is_(None))
        .order_by(SourceDocument.occurred_at.desc(), Commitment.position)
    )
    if status_filter is not None:
        query = query.where(Commitment.status == status_filter)
    if document_id is not None:
        query = query.where(Commitment.document_id == document_id)
    if counterparty is not None:
        query = query.where(Commitment.counterparty == counterparty)
    rows = (await db.execute(query)).all()
    return [_commitment_out(c, d) for c, d in rows]


async def _with_document(db: AsyncSession, row: Commitment) -> CommitmentOut:
    doc = await db.get(SourceDocument, row.document_id)
    return _commitment_out(row, doc)


@router.patch("/commitments/{commitment_id}", response_model=CommitmentOut)
async def edit_commitment(
    commitment_id: uuid.UUID,
    patch: CommitmentPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        row = await service.edit_commitment(db, user, commitment_id, patch)
    except service.NotFound:
        raise _not_found() from None
    except service.Conflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return await _with_document(db, row)


@router.post("/commitments/{commitment_id}/status", response_model=CommitmentOut)
async def change_status(
    commitment_id: uuid.UUID,
    change: StatusChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        row = await service.change_status(db, user, commitment_id, change.to, change.note)
    except service.NotFound:
        raise _not_found() from None
    except service.Conflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return await _with_document(db, row)


@router.get("/commitments/{commitment_id}/events", response_model=list[EventOut])
async def list_events(
    commitment_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
):
    try:
        await service.get_commitment(db, user, commitment_id)
    except service.NotFound:
        raise _not_found() from None
    events = (
        await db.execute(
            select(StatusEvent).where(StatusEvent.commitment_id == commitment_id).order_by(StatusEvent.created_at)
        )
    ).scalars().all()
    return [EventOut.model_validate(e) for e in events]
