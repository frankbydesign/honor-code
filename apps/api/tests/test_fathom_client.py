"""The Fathom HTTP client, against a mock transport. Never the network."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.sources.fathom import FathomClient, SourceError
from tests.conftest import load_fixture

KEY = "fathom-test-key-DO-NOT-LEAK"


def _client(handler) -> FathomClient:
    return FathomClient(api_key=KEY, transport=httpx.MockTransport(handler))


def _json(data, status=200):
    return httpx.Response(status, content=json.dumps(data).encode(), headers={"content-type": "application/json"})


async def test_list_meetings_sends_key_and_window_and_follows_cursor():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.params.get("cursor") == "cursor-page-2":
            return _json(load_fixture("fathom/meetings_page2.json"))
        return _json(load_fixture("fathom/meetings_page1.json"))

    after = datetime(2026, 10, 11, 7, 0, tzinfo=timezone.utc)
    meetings = await _client(handler).list_meetings(created_after=after)

    assert [m.recording_id for m in meetings] == [900101, 900102, 900103]
    assert len(seen) == 2
    first = seen[0]
    assert first.url.host == "api.fathom.ai"
    assert first.url.path == "/external/v1/meetings"
    assert first.headers["X-Api-Key"] == KEY
    assert first.url.params["created_after"] == "2026-10-11T07:00:00Z"
    assert first.url.params.get("include_action_items") == "true"
    assert "cursor" not in first.url.params
    assert seen[1].url.params["cursor"] == "cursor-page-2"
    assert seen[1].url.params["created_after"] == "2026-10-11T07:00:00Z"


async def test_unknown_fields_are_ignored():
    def handler(request):
        return _json(load_fixture("fathom/meetings_page2.json"))

    (meeting,) = await _client(handler).list_meetings(created_after=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert meeting.title == "Assessment data check"
    assert meeting.recorded_by.email == "frank@example.com"


async def test_get_transcript_hits_recording_path():
    seen = []

    def handler(request):
        seen.append(request)
        return _json(load_fixture("fathom/transcript_900101.json"))

    items = await _client(handler).get_transcript(900101)
    assert seen[0].url.path == "/external/v1/recordings/900101/transcript"
    assert seen[0].headers["X-Api-Key"] == KEY
    assert "destination_url" not in seen[0].url.params
    assert [i.speaker.display_name for i in items] == ["Dana Lee", "Frank Example"]
    assert items[1].speaker.matched_calendar_invitee_email == "frank@example.com"


async def test_empty_transcript_is_an_empty_list():
    items = await _client(lambda r: _json({"transcript": []})).get_transcript(1)
    assert items == []


@pytest.mark.parametrize("status_code", [401, 429, 500])
async def test_error_status_raises_source_error_without_key(status_code):
    def handler(request):
        return _json({"error": f"echo {request.headers['X-Api-Key']}"}, status=status_code)

    with pytest.raises(SourceError) as excinfo:
        await _client(handler).list_meetings(created_after=datetime(2026, 1, 1, tzinfo=timezone.utc))
    message = str(excinfo.value)
    assert str(status_code) in message
    assert KEY not in message
    assert "echo" not in message  # the response body is never copied into the error


async def test_transport_failure_raises_source_error():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect, key was {KEY}")

    with pytest.raises(SourceError) as excinfo:
        await _client(handler).get_transcript(5)
    assert KEY not in str(excinfo.value)


async def test_malformed_body_raises_source_error():
    with pytest.raises(SourceError):
        await _client(lambda r: _json({"items": [{"title": "no id"}], "next_cursor": None})).list_meetings(
            created_after=datetime(2026, 1, 1, tzinfo=timezone.utc)
        )


async def test_repeated_cursor_stops_instead_of_looping():
    def handler(request):
        page = load_fixture("fathom/meetings_page2.json")
        page["next_cursor"] = "same-cursor-forever"
        return _json(page)

    with pytest.raises(SourceError):
        await _client(handler).list_meetings(created_after=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_client_without_transport_uses_real_network_guarded_in_tests():
    # Constructing the real client must not touch the network.
    FathomClient(api_key=KEY)
