"""Spotify connector (spec §6, §23, §25).

Wraps the Spotify Web API for the **recently-played** endpoint. Authentication
is a one-time PKCE flow (no client secret — spec §23 "installed app"): the user
creates a Spotify app, sets ``SPOTIFY_CLIENT_ID`` in ``.env``, runs
``pdw auth spotify`` (``connectors/auth.py``'s ``run_spotify_oauth_flow``) to
mint a ``refresh_token`` written to ``.env``, and the connector refreshes it
for a short-lived access token once per run.

**Millisecond cursor gotcha:** Spotify's recently-played ``after`` parameter is
epoch **milliseconds** (not seconds). The incremental cursor is therefore the
newest ``played_at`` expressed as an ms string; the runner stores + forwards
it as ms (spec §12).

Notes from the official docs:
  * ``POST https://accounts.spotify.com/api/token`` — refresh the access token
    (``grant_type=refresh_token`` + ``client_id``; no secret for PKCE). A
    ``400 invalid_grant`` means the refresh token is revoked -> AuthError.
  * ``GET .../me/player/recently-played?after={ms}&limit=50`` — items each
    carry ``played_at`` (ISO) + ``track``. Pagination via the ``next`` URL,
    which already carries the cursor (no extra params on follow-up requests).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from ..models import TrackPlay
from .base import ApiError, AuthError, HttpClient, MalformedRecordError

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
API_ROOT = "https://api.spotify.com/v1"
DEFAULT_LIMIT = 50


class SpotifyTokenRefresher:
    """Exchanges a Spotify refresh token for an access token (once per run)."""

    def __init__(self, client_id: str, *, http: HttpClient) -> None:
        self._client_id = client_id
        self._http = http

    def refresh(self, refresh_token: str) -> str:
        try:
            resp = self._http.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except ApiError as exc:
            # A 400 invalid_grant / bad client is an auth/config failure
            # (spec §25); any non-2xx here aborts (no retry).
            raise AuthError(
                f"Spotify token refresh failed ({exc.status_code}) — the "
                "refresh token may be revoked; re-authorize."
            ) from exc
        body = resp.json()
        if "access_token" in body:
            return body["access_token"]
        raise AuthError(
            f"could not refresh Spotify access token: "
            f"{body.get('error', 'unknown error')}"
        )


class SpotifyClient:
    """Thin Spotify API client (httpx wrapper, injectable for tests)."""

    def __init__(self, access_token: str, *, http: HttpClient) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def get_recently_played(
        self, *, after_ms: str | None = None, limit: int = DEFAULT_LIMIT
    ) -> Iterator[list[dict]]:
        """Yield pages of recently-played items.

        ``after_ms`` is an epoch-milliseconds string; ``None`` lists with no
        ``after`` filter. Follows the ``next`` URL Spotify returns (which
        already encodes the cursor), so follow-up requests carry no params.
        """
        params: dict = {"limit": limit}
        if after_ms is not None:
            params["after"] = after_ms

        url = f"{API_ROOT}/me/player/recently-played"
        while True:
            data = self._http.get(url, headers=self._headers, **params).json()
            yield data.get("items", [])
            nxt = data.get("next")
            if not nxt:
                return
            # The `next` URL is absolute and already carries the cursor.
            url = nxt
            params = {}


class SpotifyConnector:
    """Normalizes Spotify recently-played items into shared ``TrackPlay`` records."""

    def __init__(self, client: SpotifyClient) -> None:
        self._client = client

    def fetch_recently_played(self, *, after_ms: str | None = None) -> list[TrackPlay]:
        """Fetch + normalize recently-played tracks since ``after_ms`` (ms).

        ``after_ms`` is forwarded verbatim as Spotify's ``after`` parameter;
        ``None`` lists with no filter (the runner supplies a lookback ms).
        """
        plays: list[TrackPlay] = []
        for items in self._client.get_recently_played(after_ms=after_ms):
            for item in items:
                try:
                    plays.append(self._normalize_play(item))
                except (KeyError, TypeError, ValueError) as exc:
                    raise MalformedRecordError(
                        f"could not normalize spotify play: {exc}"
                    ) from exc
        return plays

    @staticmethod
    def _normalize_play(item: dict) -> TrackPlay:
        track = item["track"]
        played_at_iso = item["played_at"]
        played_at = datetime.fromisoformat(played_at_iso.replace("Z", "+00:00"))
        track_id = track["id"]
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        # Natural key: (track_id, played_at) — the same track at different
        # times is a distinct play (recently-played items have no own id).
        return TrackPlay(
            source_id=f"{track_id}:{played_at_iso}",
            played_at=played_at,
            track_id=track_id,
            track_name=track.get("name", ""),
            artists=artists,
            raw_payload=item,
        )