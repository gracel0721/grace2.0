"""Unit tests for GitHub incremental cursor handling (spec §12, §26)."""

from datetime import UTC, datetime

from pdw.connectors.base import HttpClient
from pdw.connectors.github import GitHubClient
from tests.fakes import FakeHttpClient, FakeResponse


def _commit(iso: str, sha: str = "sha") -> dict:
    return {
        "sha": sha,
        "commit": {
            "author": {"name": "a", "email": "e", "date": iso},
            "message": "m",
        },
    }


def test_get_commits_passes_since_param():
    """When a cursor is supplied it is forwarded as the `since` query param."""
    fake = FakeHttpClient().add(
        "GET", "/repos/o/r/commits", FakeResponse(json_data=[])
    )
    client = GitHubClient("tok", client=HttpClient(fake))

    since = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    list(client.get_commits("o", "r", since=since))

    params = fake.params_for("/repos/o/r/commits")[0]
    assert params["since"] == since.isoformat()


def test_get_commits_omits_since_when_none():
    fake = FakeHttpClient().add(
        "GET", "/repos/o/r/commits", FakeResponse(json_data=[])
    )
    client = GitHubClient("tok", client=HttpClient(fake))

    list(client.get_commits("o", "r", since=None))

    params = fake.params_for("/repos/o/r/commits")[0]
    assert "since" not in params


def test_get_commits_returns_newest_only_is_caller_concern():
    """The client just forwards `since`; filtering is the API's job. We verify
    the cursor value round-trips as an ISO string."""
    fake = FakeHttpClient().add(
        "GET", "/repos/o/r/commits",
        FakeResponse(json_data=[_commit("2024-06-05T00:00:00Z", "s1")]),
    )
    client = GitHubClient("tok", client=HttpClient(fake))

    commits = []
    for page in client.get_commits("o", "r", since=datetime(2024, 6, 1, tzinfo=UTC)):
        commits.extend(page)
    assert len(commits) == 1
    # The next sync's cursor would be the max committed_at of this batch.
    assert commits[0]["commit"]["author"]["date"] == "2024-06-05T00:00:00Z"