"""Fathom's meeting shapes, and their conversion to a MeetingInput.

Field names follow the Fathom external API reference (developers.fathom.ai,
GET /external/v1/meetings and GET /recordings/{recording_id}/transcript,
checked 2026-10-24). Unknown fields are ignored, so Fathom adding fields
never breaks a sync.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.commitments.schemas import MeetingInput, Segment


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FathomSpeaker(_Lenient):
    display_name: str
    matched_calendar_invitee_email: str | None = None


class FathomTranscriptItem(_Lenient):
    speaker: FathomSpeaker
    text: str
    timestamp: str = ""


class FathomPerson(_Lenient):
    name: str | None = None
    email: str | None = None


class FathomActionItem(_Lenient):
    description: str
    user_generated: bool | None = None
    completed: bool | None = None
    recording_timestamp: str | None = None
    assignee: FathomPerson | None = None


class FathomMeeting(_Lenient):
    recording_id: int
    title: str | None = None
    meeting_title: str | None = None
    url: str | None = None
    share_url: str | None = None
    created_at: datetime
    scheduled_start_time: datetime | None = None
    recording_start_time: datetime | None = None
    recording_end_time: datetime | None = None
    recorded_by: FathomPerson | None = None
    transcript: list[FathomTranscriptItem] | None = None
    action_items: list[FathomActionItem] | None = None


def to_meeting_input(meeting: FathomMeeting, transcript: list[FathomTranscriptItem]) -> MeetingInput:
    occurred_at = meeting.recording_start_time or meeting.scheduled_start_time or meeting.created_at
    title = (meeting.title or meeting.meeting_title or "").strip() or "Untitled meeting"
    action_items: list[dict[str, Any]] | None = (
        [a.model_dump() for a in meeting.action_items] if meeting.action_items is not None else None
    )
    recorder = meeting.recorded_by or FathomPerson()
    return MeetingInput(
        external_id=str(meeting.recording_id),
        title=title[:300],
        occurred_at=occurred_at,
        source_url=meeting.share_url or meeting.url,
        recorded_by_name=recorder.name,
        recorded_by_email=recorder.email,
        segments=[
            Segment(
                speaker=item.speaker.display_name,
                email=item.speaker.matched_calendar_invitee_email,
                timestamp=item.timestamp,
                text=item.text,
            )
            for item in transcript
        ],
        vendor_action_items=action_items,
    )
