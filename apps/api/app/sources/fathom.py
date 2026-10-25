"""Fathom: the meeting shapes, their conversion to a MeetingInput, and
the HTTP client the sync uses.

Field names follow the Fathom external API reference (developers.fathom.ai,
GET /external/v1/meetings and GET /recordings/{recording_id}/transcript,
checked 2026-10-24). Unknown fields are ignored, so Fathom adding fields
never breaks a sync.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

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


# --- HTTP client -----------------------------------------------------------

FATHOM_BASE_URL = "https://api.fathom.ai/external/v1"
_MAX_PAGES = 200


class SourceError(Exception):
    """Fathom could not be reached or answered with something unusable.

    Messages are written here, never copied from Fathom's response or the
    request, so they are safe to store and show: no key, no transcript.
    """


class MeetingSource(Protocol):
    async def list_meetings(self, *, created_after: datetime) -> list[FathomMeeting]: ...

    async def get_transcript(self, recording_id: int) -> list[FathomTranscriptItem]: ...


class _MeetingsPage(_Lenient):
    items: list[FathomMeeting]
    next_cursor: str | None = None


class _TranscriptBody(_Lenient):
    transcript: list[FathomTranscriptItem] | None = None


def _utc_param(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FathomClient:
    """GET /meetings (paged) and GET /recordings/{id}/transcript."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = FATHOM_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        self._base_url = base_url

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-Api-Key": self._api_key, "Accept": "application/json"},
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, str]) -> Any:
        try:
            response = await client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"could not reach Fathom for {path} ({type(exc).__name__})") from None
        if response.status_code != 200:
            hint = {401: " (check FATHOM_API_KEY)", 429: " (rate limited; next sync will retry)"}.get(
                response.status_code, ""
            )
            raise SourceError(f"Fathom returned HTTP {response.status_code} for {path}{hint}")
        try:
            return response.json()
        except ValueError:
            raise SourceError(f"Fathom returned a body that is not JSON for {path}") from None

    async def list_meetings(self, *, created_after: datetime) -> list[FathomMeeting]:
        base = {"created_after": _utc_param(created_after), "include_action_items": "true"}
        meetings: list[FathomMeeting] = []
        seen_cursors: set[str] = set()
        cursor: str | None = None
        async with self._client() as client:
            for _ in range(_MAX_PAGES):
                params = dict(base, cursor=cursor) if cursor else dict(base)
                body = await self._get(client, "/meetings", params)
                try:
                    page = _MeetingsPage.model_validate(body)
                except ValidationError:
                    raise SourceError("Fathom returned an unexpected shape for /meetings") from None
                meetings.extend(page.items)
                cursor = page.next_cursor
                if not cursor:
                    return meetings
                if cursor in seen_cursors:
                    raise SourceError("Fathom repeated a page cursor for /meetings; stopping")
                seen_cursors.add(cursor)
        raise SourceError(f"Fathom returned more than {_MAX_PAGES} pages for /meetings; stopping")

    async def get_transcript(self, recording_id: int) -> list[FathomTranscriptItem]:
        path = f"/recordings/{int(recording_id)}/transcript"
        async with self._client() as client:
            body = await self._get(client, path, {})
        try:
            return _TranscriptBody.model_validate(body).transcript or []
        except ValidationError:
            raise SourceError(f"Fathom returned an unexpected shape for {path}") from None
