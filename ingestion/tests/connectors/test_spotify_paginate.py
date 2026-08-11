"""Unit tests for Spotify recently-played pagination + ms cursor (spec §26).

The `after` parameter is epoch **milliseconds** (not seconds). Pagination
follows the absolute `next` URL Spotify returns, which already encodes the
cursor, so follow-up requests carry no params.
"""

import pytest

from pdw.connectors.base import HttpClient, RateLimitError
from pdw.connectors.spotify import SpotifyClient
from tests.fakes import FakeHttpClient, FakeResponse


def _play(i: int) -> dict:
    return {
        "played_at": f"2024-06-0{i}T12:00:00.000Z",
        "track": {"id": f"t{i}", "name": f"Song {i}", "artists": [{"name": "A"}]},
    }


def test_get_recently_played_passes_after_ms():
    fake = FakeHttpClient().add(
        "GET", "/me/player/recently-played", FakeResponse(json_data={"items": []})
    )
    client = SpotifyClient("access", http=HttpClient(fake))

    list(client.get_recently_played(after_ms="1717588800000"))

    params = fake.params_for("/me/player/recently-played")[0]
    assert params["after"] == "1717588800000"  # ms, forwarded verbatim
    assert params["limit"] == 50


def test_get_recently_played_no_after_when_none():
    fake = FakeHttpClient().add(
        "GET", "/me/player/recently-played", FakeResponse(json_data={"items": []})
    )
    client = SpotifyClient("access", http=HttpClient(fake))

    list(client.get_recently_played())

    params = fake.params_for("/me/player/recently-played")[0]
    assert "after" not in params


def test_get_recently_played_follows_next_url():
    next_url = "https://api.spotify.com/v1/me/player/recently-played?after=999"
    fake = FakeHttpClient()
    # Register the more-specific `next` route first: the fake matches by
    # substring, and the base path is contained in the next URL.
    fake.add("GET", next_url, FakeResponse(json_data={"items": [_play(2)]}))
    fake.add(
        "GET",
        "/me/player/recently-played",
        FakeResponse(json_data={"items": [_play(1)], "next": next_url}),
    )
    client = SpotifyClient("access", http=HttpClient(fake))

    pages = list(client.get_recently_played(after_ms="0"))

    assert len(pages) == 2
    assert pages[0][0]["track"]["id"] == "t1"
    assert pages[1][0]["track"]["id"] == "t2"
    # The second request used the full `next` URL with no extra params.
    _, url2, kwargs2 = fake.requests[1]
    assert url2 == next_url
    assert (kwargs2.get("params") or {}) == {}


def test_rate_limit_raises():
    fake = FakeHttpClient().add(
        "GET", "/me/player/recently-played", FakeResponse(status_code=429, json_data={})
    )
    client = SpotifyClient("access", http=HttpClient(fake))

    with pytest.raises(RateLimitError):
        list(client.get_recently_played())