"""Phase 1 tables: where commitments come from, how they were found, and
what happened to them.

source_documents  one row per meeting (later: per email thread)
extraction_runs   one row per model call against a document
commitments       candidates a run produced, and what Frank decided
status_events     append-only history of every status change
sync_runs         one row per Fathom sync (used from Task B on)

Relationships are deliberately not mapped; the service layer queries
explicitly, which keeps loading behavior obvious under asyncio.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "external_id", name="source_documents_user_kind_external_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    recorded_by_name: Mapped[str | None] = mapped_column(String(200))
    recorded_by_email: Mapped[str | None] = mapped_column(String(320))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    speakers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    my_speaker: Mapped[str | None] = mapped_column(String(200))
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vendor_action_items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    my_speaker: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(String(500))
    raw_output: Mapped[Any | None] = mapped_column(JSON)


class Commitment(Base):
    __tablename__ = "commitments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    counterparty: Mapped[str | None] = mapped_column(String(200))
    speaker: Mapped[str | None] = mapped_column(String(200))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_found: Mapped[bool] = mapped_column(Boolean, nullable=False)
    strength: Mapped[str] = mapped_column(String(16), nullable=False)
    due_text: Mapped[str | None] = mapped_column(String(200))
    due_on: Mapped[date | None] = mapped_column(Date)
    details: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class StatusEvent(Base):
    __tablename__ = "status_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    meetings_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meetings_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meetings_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extractions_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extractions_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
