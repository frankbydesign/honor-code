"""Turning a Fathom transcript into the text the model reads.

Pure functions, no database. The rendered text is what the model sees and
what quotes are checked against, so its shape is pinned here.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.commitments.schemas import Segment
from app.commitments.transcript import identify_me, local_date, quote_found, render, speakers
from app.sources.fathom import FathomMeeting, to_meeting_input
from tests.conftest import load_fixture


def _meeting_input():
    meeting = FathomMeeting.model_validate(load_fixture("fathom/meeting_basic.json"))
    return to_meeting_input(meeting, meeting.transcript or [])


def _seg(speaker: str, text: str, email: str | None = None, ts: str = "00:00:01") -> Segment:
    return Segment(speaker=speaker, email=email, timestamp=ts, text=text)


def test_render_produces_timestamped_lines_in_order():
    rendered = render(_meeting_input().segments)
    lines = rendered.split("\n")
    assert lines[0] == "[00:00:04] Alice Kim: Thanks for making time. The board packet is due Friday."
    assert lines[1] == "[00:00:11] Frank E.: Got it. I'll send you the revised budget by Thursday."
    assert len(lines) == 5


def test_speakers_in_first_appearance_order():
    assert speakers(_meeting_input().segments) == ["Alice Kim", "Frank E."]


def test_fixture_converts_with_recorder_and_vendor_action_items():
    mi = _meeting_input()
    assert mi.external_id == "900001"
    assert mi.recorded_by_email == "frank@example.com"
    assert mi.source_url == "https://fathom.video/share/invented-token-900001"
    assert mi.vendor_action_items and mi.vendor_action_items[0]["description"] == "Send revised budget to Alice"


def test_identify_me_by_invitee_email_even_when_display_name_differs():
    segs = _meeting_input().segments
    assert identify_me(segs, name="Frank Example", email="FRANK@example.com") == "Frank E."


def test_identify_me_falls_back_to_display_name():
    segs = [_seg("Alice Kim", "hi"), _seg("Frank Example", "hello")]
    assert identify_me(segs, name="Frank Example", email="frank@example.com") == "Frank Example"


def test_identify_me_none_when_nothing_matches():
    segs = [_seg("Alice Kim", "hi", email="alice@example.org"), _seg("Speaker 2", "hello")]
    assert identify_me(segs, name="Frank Example", email="frank@example.com") is None


def test_local_date_uses_local_timezone_not_utc():
    start = datetime(2026, 10, 21, 3, 30, tzinfo=timezone.utc)
    assert local_date(start, ZoneInfo("America/Los_Angeles")).isoformat() == "2026-10-20"


def test_quote_found_tolerates_whitespace_and_curly_quotes():
    segs = _meeting_input().segments
    assert quote_found("I’ll  send you the\nrevised budget", segs)
    assert quote_found("I'll loop in Jordan", segs)  # transcript has a curly apostrophe


def test_quote_found_false_for_text_not_present():
    assert not quote_found("I'll rebuild the website", _meeting_input().segments)


def test_quote_found_false_when_quote_spans_two_entries():
    segs = _meeting_input().segments
    assert not quote_found("due Friday. Got it.", segs)


def test_quote_found_false_for_empty_quote():
    assert not quote_found("   ", _meeting_input().segments)


def test_render_large_entry_is_fast():
    big = [_seg("Alice Kim", "word " * 80_000)]  # 400,000 characters
    started = time.perf_counter()
    rendered = render(big)
    assert time.perf_counter() - started < 1.0
    assert len(rendered) > 400_000
