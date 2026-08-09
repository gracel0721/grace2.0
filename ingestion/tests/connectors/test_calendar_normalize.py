"""Unit tests for Google Calendar event normalization (spec §23, §26)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pdw.connectors.calendar import CalendarConnector

# `_normalize_event` only uses `calendar_id`, so a None client is safe here.
CONNECTOR = CalendarConnector(
    client=None,
    calendar_id="primary",  # type: ignore[arg-type]
)


def test_timed_event():
    raw = {
        "id": "evt1",
        "status": "confirmed",
        "summary": "Weekly sync",
        "start": {
            "dateTime": "2024-06-01T09:00:00-04:00",
            "timeZone": "America/New_York",
        },
        "end": {
            "dateTime": "2024-06-01T09:30:00-04:00",
            "timeZone": "America/New_York",
        },
        "attendees": [{"email": "a@x"}, {"email": "b@x"}],
    }
    ev = CONNECTOR._normalize_event(raw)
    assert ev.source_id == "evt1"
    assert ev.calendar_id == "primary"
    assert ev.title == "Weekly sync"
    assert ev.timezone == "America/New_York"
    assert ev.attendees_count == 2
    assert ev.status == "confirmed"
    assert ev.category == "meeting"
    assert ev.raw_payload is raw
    # end - start == 30 minutes
    assert ev.end_at - ev.start_at == timedelta(minutes=30)


def test_all_day_event_end_is_exclusive_plus_one_day():
    """All-day events use date-only `end` which is exclusive (spec/docs)."""
    raw = {
        "id": "evt2",
        "status": "confirmed",
        "summary": "OOO",
        "start": {"date": "2024-06-10", "timeZone": "America/New_York"},
        "end": {"date": "2024-06-11", "timeZone": "America/New_York"},
    }
    ev = CONNECTOR._normalize_event(raw)
    # start = midnight on the 10th in the event tz; end = end.date + 1 day.
    ny = ZoneInfo("America/New_York")
    assert ev.start_at == datetime(2024, 6, 10, tzinfo=ny)
    assert ev.end_at == datetime(2024, 6, 12, tzinfo=ny)
    assert ev.end_at - ev.start_at == timedelta(days=2)


def test_cancelled_event_loaded_with_nulls():
    """Cancelled events keep their id + status so dbt can filter them out."""
    raw = {"id": "evt3", "status": "cancelled"}
    ev = CONNECTOR._normalize_event(raw)
    assert ev.status == "cancelled"
    assert ev.title == ""
    assert ev.attendees_count == 0
    assert ev.category == "other"


def test_category_via_categorize():
    raw = {
        "id": "evt4",
        "status": "confirmed",
        "summary": "Gym",
        "start": {"dateTime": "2024-06-01T12:00:00Z", "timeZone": "UTC"},
        "end": {"dateTime": "2024-06-01T13:00:00Z", "timeZone": "UTC"},
    }
    ev = CONNECTOR._normalize_event(raw)
    assert ev.category == "personal"
