"""Unit tests for GitHub issues incremental cursor handling (spec §12, §26)."""

from datetime import UTC, datetime

from pdw.connectors.base import HttpClient
from pdw.connectors.github import GitHubClient
from tests.fakes import FakeHttpClient, FakeResponse


def test_get_issues_passes_since_param():
    """When a cursor is supplied it is forwarded as the `since` query param."""
    fake = FakeHttpClient().add("GET", "/repos/o/r/issues", FakeResponse(json_data=[]))
    client = GitHubClient("tok", client=HttpClient(fake))

    since = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    list(client.get_issues("o", "r", since=since))

    params = fake.params_for("/repos/o/r/issues")[0]
    assert params["since"] == since.isoformat()


def test_get_issues_omits_since_when_none():
    fake = FakeHttpClient().add("GET", "/repos/o/r/issues", FakeResponse(json_data=[]))
    client = GitHubClient("tok", client=HttpClient(fake))

    list(client.get_issues("o", "r", since=None))

    params = fake.params_for("/repos/o/r/issues")[0]
    assert "since" not in params
