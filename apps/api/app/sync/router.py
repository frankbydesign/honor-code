"""GET /api/sync (status) and POST /api/sync (Sync now)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings
from app.auth.deps import get_current_user
from app.commitments.extraction import Extractor
from app.commitments.router import get_extractor
from app.db.models import SyncRun, User
from app.db.session import get_session
from app.sources.fathom import FathomClient, MeetingSource
from app.sync import service

router = APIRouter(tags=["sync"])


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    trigger: str
    status: str
    window_start: datetime
    started_at: datetime
    finished_at: datetime | None
    meetings_seen: int
    meetings_new: int
    meetings_pending: int
    extractions_ok: int
    extractions_failed: int
    error: str | None


class SyncStatus(BaseModel):
    configured: bool
    missing: list[str]
    running: bool
    last_run: SyncRunOut | None


class SyncStarted(BaseModel):
    run: SyncRunOut


def get_meeting_source() -> MeetingSource | None:
    key = settings.fathom_api_key()
    return FathomClient(api_key=key) if key else None


@router.get("/sync", response_model=SyncStatus)
async def sync_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    missing = settings.missing_for_sync()
    last = (
        await db.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
    ).scalar_one_or_none()
    return SyncStatus(
        configured=not missing,
        missing=missing,
        running=service.is_running(),
        last_run=SyncRunOut.model_validate(last) if last else None,
    )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, response_model=SyncStarted)
async def sync_now(
    user: User = Depends(get_current_user),
    source: MeetingSource | None = Depends(get_meeting_source),
    extractor: Extractor | None = Depends(get_extractor),
):
    missing = settings.missing_for_sync()
    if missing or source is None or extractor is None:
        names = ", ".join(missing) or "FATHOM_API_KEY, ANTHROPIC_API_KEY"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"sync is not configured: set {names} in apps/api/.env",
        )
    try:
        run = await service.start_sync("manual", source=source, extractor=extractor)
    except service.SyncInProgress:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="a sync is already running") from None
    return SyncStarted(run=SyncRunOut.model_validate(run))
