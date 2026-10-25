"""Pydantic shapes: what goes in (meetings, model output, edits) and what
the API sends back."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.commitments.enums import CommitmentStatus, DocumentKind, Strength

# --- Input to the store ----------------------------------------------------


class Segment(BaseModel):
    """One speaker turn, source-neutral."""

    speaker: str
    email: str | None = None
    timestamp: str = ""
    text: str


class MeetingInput(BaseModel):
    """Everything store_meeting needs, already converted from the source."""

    kind: DocumentKind = DocumentKind.FATHOM_MEETING
    external_id: str = Field(min_length=1, max_length=128)
    title: str
    occurred_at: AwareDatetime
    source_url: str | None = None
    recorded_by_name: str | None = None
    recorded_by_email: str | None = None
    segments: list[Segment]
    vendor_action_items: list[dict[str, Any]] | None = None


# --- Model output ----------------------------------------------------------


def _strip_or_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class Candidate(BaseModel):
    """One commitment as the model reports it. Unknown keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1, max_length=500)
    counterparty: str | None = Field(default=None, max_length=200)
    speaker: str | None = Field(default=None, max_length=200)
    quote: str = Field(min_length=1)
    strength: Strength
    due_text: str | None = Field(default=None, max_length=200)
    due_on: date | None = None
    details: str | None = None

    @field_validator("summary", "quote", mode="before")
    @classmethod
    def _strip_required(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("counterparty", "speaker", "due_text", "details", mode="before")
    @classmethod
    def _strip_optional(cls, value: Any) -> Any:
        return _strip_or_none(value)


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    commitments: list[Candidate]


# --- Requests --------------------------------------------------------------


class CommitmentPatch(BaseModel):
    """Editable fields. Anything else in the body is a 422."""

    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, max_length=500)
    counterparty: str | None = Field(default=None, max_length=200)
    due_text: str | None = Field(default=None, max_length=200)
    due_on: date | None = None
    details: str | None = None
    strength: Strength | None = None

    @field_validator("summary", mode="before")
    @classmethod
    def _summary_not_blank(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("summary cannot be cleared")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("summary cannot be empty")
        return value

    @field_validator("counterparty", "due_text", "details", mode="before")
    @classmethod
    def _strip_optional(cls, value: Any) -> Any:
        return _strip_or_none(value)

    @field_validator("strength", mode="before")
    @classmethod
    def _strength_not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("strength cannot be cleared")
        return value


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: CommitmentStatus
    note: str | None = Field(default=None, max_length=2000)


# --- Responses -------------------------------------------------------------


class _FromRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RunOut(_FromRow):
    id: uuid.UUID
    document_id: uuid.UUID
    status: str
    model: str
    prompt_version: str
    my_speaker: str | None
    input_tokens: int | None
    output_tokens: int | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class DocumentRef(BaseModel):
    id: uuid.UUID
    title: str
    occurred_on: date


class CommitmentOut(_FromRow):
    id: uuid.UUID
    document_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    summary: str
    counterparty: str | None
    speaker: str | None
    quote: str
    quote_found: bool
    strength: str
    due_text: str | None
    due_on: date | None
    details: str | None
    position: int
    created_at: datetime
    updated_at: datetime
    document: DocumentRef | None = None


class EventOut(_FromRow):
    id: uuid.UUID
    commitment_id: uuid.UUID
    from_status: str | None
    to_status: str
    note: str | None
    created_at: datetime


class StatusCounts(BaseModel):
    candidate: int = 0
    accepted: int = 0
    done: int = 0
    rejected: int = 0
    dropped: int = 0


class DocumentSummary(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    occurred_at: datetime
    occurred_on: date
    source_url: str | None
    char_count: int
    counts: StatusCounts


class DocumentDetail(DocumentSummary):
    raw_text: str
    speakers: list[str]
    my_speaker: str | None
    recorded_by_name: str | None
    recorded_by_email: str | None
    vendor_action_items: list[dict[str, Any]] | None
    runs: list[RunOut]
    commitments: list[CommitmentOut]


class ExtractResponse(BaseModel):
    run: RunOut
    commitments: list[CommitmentOut]
