"""The extraction seam: one model call that returns candidate commitments.

Everything outside this module talks to an `Extractor`, which takes the
system prompt and the user message and returns the raw tool input plus
usage. Tests swap in a fake at that seam (tests/fakes.py). Validating what
comes back is the service's job, so a fake returning a malformed payload
exercises the same path a misbehaving model would.

AnthropicExtractor forces a single `record_commitments` tool call
(tool_choice type "tool"), so the answer arrives as structured input and
never as free text. Checked against anthropic 2.3.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, Protocol

PROMPT_VERSION = "v1"
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
TOOL_NAME = "record_commitments"
MAX_OUTPUT_TOKENS = 8000


@cache
def system_prompt(version: str = PROMPT_VERSION) -> str:
    return (_PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")


@dataclass(frozen=True)
class ExtractionContext:
    title: str
    meeting_date: date
    my_speaker: str | None
    my_name: str | None
    my_email: str | None


def build_user_message(transcript: str, ctx: ExtractionContext) -> str:
    who = ctx.my_name or "the person who recorded this meeting"
    if ctx.my_email:
        who += f" ({ctx.my_email})"
    if ctx.my_speaker:
        label = f'Their speaker label in this transcript is "{ctx.my_speaker}".'
    else:
        label = (
            "Their speaker label was not matched automatically; work out which "
            "speaker they are from the name and the conversation. If you cannot "
            "tell, report no commitments."
        )
    return (
        f"Meeting: {ctx.title}\n"
        f"Meeting date: {ctx.meeting_date.isoformat()}\n"
        f"The person is: {who}. {label}\n"
        "Find only this person's commitments.\n\n"
        "<transcript>\n"
        f"{transcript}\n"
        "</transcript>"
    )


TOOL_SCHEMA: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": "Record every commitment the named person made in this meeting. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "commitments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "counterparty": {"type": ["string", "null"]},
                        "speaker": {"type": ["string", "null"]},
                        "quote": {"type": "string"},
                        "strength": {"type": "string", "enum": ["firm", "soft", "offer"]},
                        "due_text": {"type": ["string", "null"]},
                        "due_on": {"type": ["string", "null"], "description": "YYYY-MM-DD or null"},
                        "details": {"type": ["string", "null"]},
                    },
                    "required": ["summary", "counterparty", "speaker", "quote", "strength", "due_text", "due_on", "details"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["commitments"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class ExtractionResult:
    raw: Any
    model: str
    input_tokens: int | None
    output_tokens: int | None


class ExtractorError(Exception):
    """The model answered, but not with the tool call we asked for."""


class Extractor(Protocol):
    model: str

    async def extract(self, *, system: str, user: str) -> ExtractionResult: ...


class AnthropicExtractor:
    def __init__(self, *, api_key: str, model: str, timeout: float, max_retries: int = 2) -> None:
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = None  # built on first use, so constructing never touches the network

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(
                api_key=self._api_key, timeout=self._timeout, max_retries=self._max_retries
            )
        return self._client

    async def extract(self, *, system: str, user: str) -> ExtractionResult:
        message = await self._get_client().messages.create(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": TOOL_NAME, "disable_parallel_tool_use": True},
        )
        blocks = [b for b in message.content if getattr(b, "type", None) == "tool_use" and b.name == TOOL_NAME]
        if len(blocks) != 1:
            raise ExtractorError(f"expected one {TOOL_NAME} call, got {len(blocks)}")
        usage = getattr(message, "usage", None)
        return ExtractionResult(
            raw=blocks[0].input,
            model=getattr(message, "model", None) or self.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
