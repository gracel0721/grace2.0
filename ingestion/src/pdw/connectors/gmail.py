"""Gmail connector (spec §3, §6, §23, §25).

Wraps the Gmail API. Authentication reuses the Google OAuth refresh token from
``connectors/calendar.py``'s ``GoogleTokenRefresher`` — the one-time
``pdw auth google`` flow (``connectors/auth.py``) now requests
``gmail.readonly`` alongside ``calendar.readonly``/``spreadsheets.readonly``,
so a single refresh token authorizes every Google source.

Per spec §3/§23 this connector is **metadata only**: it stores the From/To/
Subject/Date headers and the ``snippet`` (a ~200-char preview Gmail generates),
never the message body. We fetch with ``format=metadata`` + a restricted
``metadataHeaders`` list so the body is not transmitted in the first place.

Incremental sync uses Gmail's search ``q=after:YYYY/MM/DD`` (date-granular only;
Gmail has no timestamp-level "updated since"). The overlap on the cursor day is
harmless because raw upserts are idempotent (spec §13).

Notes from the official docs:
  * ``GET .../users/me/messages?q=&maxResults=&pageToken=`` — list message stubs
    ``{id, threadId}``; paginate via ``nextPageToken``. ``maxResults`` <= 500.
  * ``GET .../users/me/messages/{id}?format=metadata`` — full message with
    ``internalDate`` (epoch ms), ``snippet``, and ``payload.headers`` (a list
    of ``{name, value}``); ``metadataHeaders`` restricts which headers return.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from ..models import Email
from .base import HttpClient, MalformedRecordError

API_ROOT = "https://gmail.googleapis.com/gmail/v1"
MAX_RESULTS = 500
# Restricted metadataHeaders (spec §23): no body, no full header dump.
METADATA_HEADERS = ["From", "To", "Subject", "Date"]


class GmailClient:
    """Thin Gmail API client (httpx wrapper, injectable for tests)."""

    def __init__(
        self,
        access_token: str,
        *,
        http: HttpClient | None = None,
    ) -> None:
        self._http = http or HttpClient(httpx.Client(timeout=30.0))
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def list_messages(
        self, *, q: str | None = None, max_results: int = MAX_RESULTS
    ) -> Iterator[list[dict]]:
        """Yield pages of message stubs ``{id, threadId}``."""
        params: dict = {"maxResults": max_results}
        if q is not None:
            params["q"] = q

        page_token: str | None = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            data = self._http.get(
                f"{API_ROOT}/users/me/messages",
                headers=self._headers,
                **params,
            ).json()
            yield data.get("messages", [])
            page_token = data.get("nextPageToken")
            if not page_token:
                return

    def get_message(self, msg_id: str) -> dict:
        """Fetch one message metadata-only (spec §23: no body)."""
        return self._http.get(
            f"{API_ROOT}/users/me/messages/{msg_id}",
            headers=self._headers,
            format="metadata",
            metadataHeaders=METADATA_HEADERS,
        ).json()


class GmailConnector:
    """Normalizes Gmail messages into shared ``Email`` records (metadata only)."""

    def __init__(self, client: GmailClient) -> None:
        self._client = client

    def fetch_messages(self, *, after: str | None = None) -> list[Email]:
        """Fetch + normalize messages metadata-only.

        ``after`` is a Gmail search date string ``YYYY/MM/DD`` used as
        ``q=after:{after}`` for incremental sync; ``None`` lists with no date
        filter (backfill relies on the runner passing a lookback date).
        """
        q = f"after:{after}" if after else None
        emails: list[Email] = []
        for stubs in self._client.list_messages(q=q):
            for stub in stubs:
                try:
                    msg_id = stub["id"]
                    raw = self._client.get_message(msg_id)
                    emails.append(self._normalize_message(raw))
                except (KeyError, TypeError, ValueError) as exc:
                    raise MalformedRecordError(
                        f"could not normalize gmail message: {exc}"
                    ) from exc
        return emails

    @staticmethod
    def _normalize_message(raw: dict) -> Email:
        headers = {
            h["name"]: h["value"]
            for h in (raw.get("payload") or {}).get("headers", [])
        }
        # internalDate is epoch milliseconds (string); always present.
        date = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=UTC)
        return Email(
            source_id=raw["id"],
            thread_id=raw.get("threadId", ""),
            sender=headers.get("From", ""),
            recipients=headers.get("To", ""),
            subject=headers.get("Subject", ""),
            date=date,
            snippet=raw.get("snippet", ""),
            raw_payload=raw,
        )