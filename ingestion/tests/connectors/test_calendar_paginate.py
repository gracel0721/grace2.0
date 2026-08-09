"""Unit tests for Google Calendar pagination (spec §26)."""

from pdw.connectors.base import HttpClient
from pdw.connectors.calendar import CalendarClient
from tests.fakes import FakeHttpClient, FakeResponse


def _event(i: int) -> dict:
    return {
        "id": f"evt-{i}",
        "status": "confirmed",
        "summary": "Weekly sync",
        "start": {"dateTime": "2024-06-01T09:00:00Z", "timeZone": "UTC"},
        "end": {"dateTime": "2024-06-01T09:30:00Z", "timeZone": "UTC"},
    }


def test_get_events_paginates_via_page_token():
    fake = FakeHttpClient()
    fake.add(
        "GET",
        "/calendars/primary/events",
        FakeResponse(
            json_data={"items": [_event(0), _event(1)], "nextPageToken": "tok2"}
        ),
        FakeResponse(json_data={"items": [_event(2)]}),  # no nextPageToken -> stop
    )
    client = CalendarClient("access", http=HttpClient(fake))

    pages = list(client.get_events("primary"))

    assert len(pages) == 2
    assert len(pages[0]) == 2
    assert len(pages[1]) == 1
    # second request carries the pageToken
    params = fake.params_for("/calendars/primary/events")
    assert "pageToken" not in params[0]
    assert params[1]["pageToken"] == "tok2"


def test_get_events_passes_updated_min():
    from datetime import UTC, datetime

    fake = FakeHttpClient().add(
        "GET", "/calendars/primary/events", FakeResponse(json_data={"items": []})
    )
    client = CalendarClient("access", http=HttpClient(fake))

    updated = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    list(client.get_events("primary", updated_min=updated))

    params = fake.params_for("/calendars/primary/events")[0]
    assert params["updatedMin"] == updated.isoformat()
    assert params["singleEvents"] == "true"
    assert params["orderBy"] == "startTime"
