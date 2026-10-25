"""Test doubles for the external seams.

FakeExtractor stands in for the Anthropic model. Each test tells it what
to do (return candidates, return a malformed payload, or raise), and it
records every prompt it was given so tests can assert on what the model
would have seen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.commitments.extraction import ExtractionResult


def candidate(**overrides: Any) -> dict[str, Any]:
    """One well-formed candidate as the model would return it."""
    data: dict[str, Any] = {
        "summary": "Send Alice the revised budget",
        "counterparty": "Alice Kim",
        "speaker": "Frank E.",
        "quote": "I'll send you the revised budget by Thursday.",
        "strength": "firm",
        "due_text": "by Thursday",
        "due_on": "2026-10-22",
        "details": None,
    }
    data.update(overrides)
    return data


@dataclass
class FakeExtractor:
    model: str = "fake-model"
    raw: Any = field(default_factory=lambda: {"commitments": []})
    error: BaseException | None = None
    input_tokens: int = 1200
    output_tokens: int = 150
    calls: list[dict[str, str]] = field(default_factory=list)

    def returns(self, commitments: list[dict[str, Any]]) -> None:
        self.raw = {"commitments": commitments}
        self.error = None

    def returns_raw(self, raw: Any) -> None:
        self.raw = raw
        self.error = None

    def raises(self, exc: BaseException) -> None:
        self.error = exc

    async def extract(self, *, system: str, user: str) -> ExtractionResult:
        self.calls.append({"system": system, "user": user})
        if self.error is not None:
            raise self.error
        return ExtractionResult(
            raw=self.raw,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class FakeMeetingSource:
    """Stands in for Fathom. Serves meetings and transcripts from memory.

    `meetings` are FathomMeeting objects; `transcripts` maps recording id to
    a list of FathomTranscriptItem. A recording id missing from
    `transcripts` returns an empty transcript (Fathom still processing).
    `gate`, when set, makes list_meetings wait on it, so a test can hold a
    sync open.
    """

    def __init__(self, meetings=None, transcripts=None):
        self.meetings = list(meetings or [])
        self.transcripts = dict(transcripts or {})
        self.list_error: BaseException | None = None
        self.transcript_errors: dict[int, BaseException] = {}
        self.list_calls: list[Any] = []
        self.transcript_calls: list[int] = []
        self.gate = None

    async def list_meetings(self, *, created_after):
        self.list_calls.append(created_after)
        if self.gate is not None:
            await self.gate.wait()
        if self.list_error is not None:
            raise self.list_error
        return [m for m in self.meetings if m.created_at >= created_after]

    async def get_transcript(self, recording_id: int):
        self.transcript_calls.append(recording_id)
        if recording_id in self.transcript_errors:
            raise self.transcript_errors[recording_id]
        return list(self.transcripts.get(recording_id, []))


def fathom_fixture_source():
    """A FakeMeetingSource loaded with the three invented sync meetings."""
    from app.sources.fathom import FathomMeeting, FathomTranscriptItem
    from tests.conftest import load_fixture

    meetings = [
        FathomMeeting.model_validate(item)
        for page in ("fathom/meetings_page1.json", "fathom/meetings_page2.json")
        for item in load_fixture(page)["items"]
    ]
    transcripts = {
        m.recording_id: [
            FathomTranscriptItem.model_validate(t)
            for t in load_fixture(f"fathom/transcript_{m.recording_id}.json")["transcript"]
        ]
        for m in meetings
    }
    return FakeMeetingSource(meetings, transcripts)
