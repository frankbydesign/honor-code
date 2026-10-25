"""Transcript helpers: render for the model, find Frank, check quotes.

All pure functions over Segment lists, so they are cheap to test and have
no idea where the transcript came from.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.commitments.schemas import Segment

_QUOTE_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "–": "-",
        "—": "-",
        " ": " ",
    }
)
_WS = re.compile(r"\s+")


def render_line(segment: Segment) -> str:
    stamp = f"[{segment.timestamp}] " if segment.timestamp else ""
    return f"{stamp}{segment.speaker}: {segment.text}"


def render(segments: Iterable[Segment]) -> str:
    """One line per turn: "[HH:MM:SS] Speaker: text"."""
    return "\n".join(render_line(s) for s in segments)


def speakers(segments: Iterable[Segment]) -> list[str]:
    """Display names in the order they first speak."""
    seen: dict[str, None] = {}
    for s in segments:
        seen.setdefault(s.speaker, None)
    return list(seen)


def identify_me(segments: list[Segment], *, name: str | None, email: str | None) -> str | None:
    """The speaker label that is the recorder (Frank), or None.

    Email match first, because Fathom ties a speaker to a calendar invitee
    by email and display names vary ("Frank E." vs "Frank Example"). Then an
    exact, case-insensitive display-name match. Otherwise None, and the
    prompt asks the model to work it out from the name and email.
    """
    if email:
        wanted = email.strip().lower()
        for s in segments:
            if s.email and s.email.strip().lower() == wanted:
                return s.speaker
    if name:
        wanted_name = name.strip().casefold()
        for s in segments:
            if s.speaker.strip().casefold() == wanted_name:
                return s.speaker
    return None


def local_date(moment: datetime, tz: ZoneInfo) -> date:
    return moment.astimezone(tz).date()


def _normalize(text: str) -> str:
    return _WS.sub(" ", text.translate(_QUOTE_FOLD)).strip().casefold()


def quote_found(quote: str, segments: Iterable[Segment]) -> bool:
    """True when the quote appears within a single speaker turn.

    Whitespace, letter case, and curly versus straight quotes are ignored.
    A quote stitched across two turns is not a quote anyone said, so it
    does not count.
    """
    needle = _normalize(quote or "")
    if not needle:
        return False
    return any(needle in _normalize(s.text) for s in segments)
