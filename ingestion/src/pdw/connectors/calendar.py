"""Google Calendar connector (spec §6, §23, §25).

Wraps the Google Calendar API. Authentication uses an OAuth refresh token
exchanged for a short-lived access token once per run (spec §23: tokens are
kept in memory / environment, never stored in PostgreSQL).

Incremental syncs use ``updatedMin`` (returns modified + cancelled events),
while the initial backfill uses ``timeMin``/``timeMax`` over a lookback window.

Notes from the official docs:
  * ``POST https://oauth2.googleapis.com/token`` — refresh the access token.
    A ``400 invalid_grant`` means the refresh token is revoked -> AuthError.
  * ``GET .../calendars/{id}/events`` — list events. ``singleEvents=true``
    expands recurring events; ``orderBy=startTime`` requires singleEvents.
    Pagination via ``pageToken``/``nextPageToken``. ``maxResults`` <= 2500.
  * All-day events use ``start.date``/``end.date`` (date-only, ``end`` is
    **exclusive**); timed events use ``start.dateTime``/``end.dateTime``.
  * Cancelled events appear with ``status='cancelled'`` and no summary/times.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ..models import CalendarEvent
from ..synthetic.categorize import categorize
from .base import ApiError, AuthError, HttpClient, MalformedRecordError

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_ROOT = "https://www.googleapis.com/calendar/v3"
MAX_RESULTS = 2500


def _parse_dt(value: str, tz: str | None) -> datetime:
    """Parse an ISO-8601 timestamp, attaching ``tz`` if it lacks an offset."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None and tz:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        except Exception:  # unknown tz id -> fall back to UTC
            dt = dt.replace(tzinfo=UTC)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _parse_date(value: str, tz: str | None) -> datetime:
    """Parse a date-only value (YYYY-MM-DD) as midnight in ``tz`` (or UTC)."""
    dt = datetime.fromisoformat(value)
    if tz:
        try:
            return dt.replace(tzinfo=ZoneInfo(tz))
        except Exception:
            pass
    return dt.replace(tzinfo=UTC)


class GoogleTokenRefresher:
    """Exchanges a refresh token for an access token (once per run)."""

    def __init__(self, client_id: str, client_secret: str, *, http: HttpClient) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http

    def refresh(self, refresh_token: str) -> str:
        try:
            resp = self._http.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except ApiError as exc:
            # The token endpoint returns 400 for invalid_grant / bad client;
            # any non-2xx here is an auth/config failure (spec §25).
            raise AuthError(
                f"token refresh failed ({exc.status_code}) — the refresh token "
                "may be revoked; re-authorize."
            ) from exc
        body = resp.json()
        if "access_token" in body:
            return body["access_token"]
        raise AuthError(
            f"could not refresh access token: {body.get('error', 'unknown error')}"
        )


class CalendarClient:
    """Thin Google Calendar API client (httpx wrapper, injectable for tests)."""

    def __init__(
        self,
        access_token: str,
        *,
        http: HttpClient,
    ) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def get_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        updated_min: datetime | None = None,
    ) -> Iterator[list[dict]]:
        """Yield pages of events for a calendar."""
        params: dict = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": MAX_RESULTS,
        }
        if time_min is not None:
            params["timeMin"] = time_min.isoformat()
        if time_max is not None:
            params["timeMax"] = time_max.isoformat()
        if updated_min is not None:
            params["updatedMin"] = updated_min.isoformat()

        page_token: str | None = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            data = self._http.get(
                f"{API_ROOT}/calendars/{calendar_id}/events",
                headers=self._headers,
                **params,
            ).json()
            yield data.get("items", [])
            page_token = data.get("nextPageToken")
            if not page_token:
                return


class CalendarConnector:
    """Normalizes Google Calendar events into shared records."""

    def __init__(self, client: CalendarClient, *, calendar_id: str) -> None:
        self._client = client
        self._calendar_id = calendar_id

    def fetch_events(
        self,
        *,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        updated_min: datetime | None = None,
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for page in self._client.get_events(
            self._calendar_id,
            time_min=time_min,
            time_max=time_max,
            updated_min=updated_min,
        ):
            for raw in page:
                try:
                    events.append(self._normalize_event(raw))
                except (KeyError, TypeError) as exc:
                    raise MalformedRecordError(
                        f"could not normalize calendar event: {exc}"
                    ) from exc
        return events

    def _normalize_event(self, raw: dict) -> CalendarEvent:
        eid = raw["id"]
        status = raw.get("status", "confirmed")
        start = raw.get("start") or {}
        end = raw.get("end") or {}
        tz = start.get("timeZone") or "UTC"

        if "dateTime" in start:
            start_at = _parse_dt(start["dateTime"], start.get("timeZone"))
            end_at = _parse_dt(end["dateTime"], end.get("timeZone"))
        elif "date" in start:
            # All-day event: date-only, end is exclusive -> add a day.
            start_at = _parse_date(start["date"], tz)
            end_at = _parse_date(end["date"], tz) + timedelta(days=1)
        else:
            # Cancelled / malformed events carry no timing; store nulls so dbt
            # can filter them out by status (spec §23).
            start_at = None
            end_at = None
            tz = "UTC"

        attendees = raw.get("attendees") or []
        summary = raw.get("summary") or ""
        return CalendarEvent(
            source_id=eid,
            calendar_id=self._calendar_id,
            title=summary,
            start_at=start_at,
            end_at=end_at,
            timezone=tz,
            attendees_count=len(attendees),
            status=status,
            category=categorize(summary) if summary else "other",
            raw_payload=raw,
        )