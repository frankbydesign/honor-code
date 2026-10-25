"""Measuring extraction against Frank's real meetings (ADR 0002).

The pieces scripts/eval_extraction.py is built from, kept here so they can
be tested offline: loading a saved meeting, scoring a list of found
commitments against a hand-written list, and formatting a report.

Scoring is deliberately simple. A found commitment matches an expected one
when their summaries are similar enough (difflib ratio on lowercased,
whitespace-collapsed text), each expected item matching at most once. That
is crude, but it is the same crude ruler for every model and prompt
version, which is what a comparison needs.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.sources.fathom import FathomMeeting, FathomTranscriptItem

MATCH_THRESHOLD = 0.6
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


@dataclass(frozen=True)
class Score:
    expected: int
    found: int
    matched: int

    @property
    def precision(self) -> float | None:
        return self.matched / self.found if self.found else None

    @property
    def recall(self) -> float | None:
        return self.matched / self.expected if self.expected else None


def score(expected: Sequence[str], found: Sequence[str], threshold: float = MATCH_THRESHOLD) -> Score:
    """Greedy one-to-one matching, best pairs first."""
    pairs = sorted(
        ((similarity(e, f), i, j) for i, e in enumerate(expected) for j, f in enumerate(found)),
        reverse=True,
    )
    used_e: set[int] = set()
    used_f: set[int] = set()
    for ratio, i, j in pairs:
        if ratio < threshold:
            break
        if i in used_e or j in used_f:
            continue
        used_e.add(i)
        used_f.add(j)
    return Score(expected=len(expected), found=len(found), matched=len(used_e))


def vendor_items_for(meeting: FathomMeeting) -> list[str]:
    """Fathom's own action items assigned to the recorder: the baseline."""
    me = (meeting.recorded_by.email or "").lower() if meeting.recorded_by else ""
    return [
        a.description
        for a in meeting.action_items or []
        if a.assignee and a.assignee.email and a.assignee.email.lower() == me
    ]


def load_saved_meeting(path: Path) -> tuple[FathomMeeting, list[FathomTranscriptItem]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    meeting = FathomMeeting.model_validate(data["meeting"])
    transcript = [FathomTranscriptItem.model_validate(t) for t in data["transcript"]]
    return meeting, transcript


def load_expected(path: Path) -> list[str] | None:
    """A hand-written list of the commitments Frank knows he made.

    Either a JSON list of strings, or {"commitments": [...]}.
    """
    if not path.exists():
        return None
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("commitments", []) if isinstance(data, dict) else data
    return [str(x) for x in items]


def saved_meeting_files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.glob("*.json") if not p.name.endswith(".expected.json")
    )


def group_report(candidates: Iterable[dict[str, Any]]) -> str:
    """Candidates grouped by counterparty, the way the Review screen shows them."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        groups.setdefault(c.get("counterparty") or "No one in particular", []).append(c)
    order = sorted(groups, key=lambda k: (k == "No one in particular", k.lower()))
    lines: list[str] = []
    for key in order:
        lines.append(f"  {key}")
        for c in groups[key]:
            due = f" ({c['due_text']})" if c.get("due_text") else ""
            lines.append(f"    - [{c.get('strength', '?')}] {c.get('summary', '')}{due}")
    return "\n".join(lines) if lines else "  (no commitments found)"


def format_score(label: str, s: Score) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.0%}"

    return (
        f"  {label}: matched {s.matched} of {s.expected} expected, {s.found} found"
        f" · precision {pct(s.precision)} · recall {pct(s.recall)}"
    )


def is_git_ignored(path: Path) -> bool:
    """True when git would ignore `path`. Eval data must never be committed."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=path.parent if path.parent.exists() else None,
            capture_output=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0
