"""Unit tests for Spotify recently-played normalization (spec §6, §26)."""

from datetime import UTC, datetime

from pdw.connectors.spotify import SpotifyConnector

# `_normalize_play` is a static method with no client dependency.
CONNECTOR = SpotifyConnector(client=None)  # type: ignore[arg-type]


def _item(track_id="t1", played_at="2024-06-05T12:00:00.000Z", artists=None, name="Song"):
    return {
        "played_at": played_at,
        "track": {
            "id": track_id,
            "name": name,
            "artists": artists if artists is not None else [{"name": "A"}, {"name": "B"}],
        },
    }


def test_normalize_play():
    play = CONNECTOR._normalize_play(_item())
    assert play.source_id == "t1:2024-06-05T12:00:00.000Z"
    assert play.played_at == datetime(2024, 6, 5, 12, 0, tzinfo=UTC)
    assert play.track_id == "t1"
    assert play.track_name == "Song"
    assert play.artists == "A, B"
    assert play.raw_payload["track"]["id"] == "t1"


def test_normalize_multi_artist_join():
    play = CONNECTOR._normalize_play(
        _item(artists=[{"name": "X"}, {"name": "Y"}, {"name": "Z"}])
    )
    assert play.artists == "X, Y, Z"


def test_normalize_no_artists():
    play = CONNECTOR._normalize_play(_item(artists=[]))
    assert play.artists == ""


def test_source_id_distinguishes_same_track_different_time():
    a = CONNECTOR._normalize_play(_item(played_at="2024-06-05T12:00:00.000Z"))
    b = CONNECTOR._normalize_play(_item(played_at="2024-06-06T12:00:00.000Z"))
    assert a.source_id != b.source_id  # same track id, distinct plays
    assert a.track_id == b.track_id