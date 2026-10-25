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
