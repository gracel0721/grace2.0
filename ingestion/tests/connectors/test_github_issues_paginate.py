"""Unit tests for GitHub issues pagination (spec §26)."""

from pdw.connectors.base import HttpClient
from pdw.connectors.github import GitHubClient
from tests.fakes import FakeHttpClient, FakeResponse


def _item(i: int, pr: bool = False) -> dict:
    base = {
        "node_id": f"n{i}",
        "number": i,
        "title": f"t{i}",
        "state": "open",
        "user": {"login": "g"},
        "created_at": "2024-06-01T00:00:00Z",
        "updated_at": "2024-06-01T00:00:00Z",
        "closed_at": None,
        "comments": 0,
    }
    if pr:
        base["pull_request"] = {"url": "u"}
    return base


def test_get_issues_paginates_until_short_page():
    fake = FakeHttpClient()
    page1 = [_item(i) for i in range(100)]
    page2 = [_item(i) for i in range(100, 135)]  # short page -> stop
    fake.add(
        "GET",
        "/repos/o/r/issues",
        FakeResponse(json_data=page1),
        FakeResponse(json_data=page2),
    )
    client = GitHubClient("tok", client=HttpClient(fake))

    pages = [p for p in client.get_issues("o", "r")]

    assert len(pages) == 2
    assert len(pages[0]) == 100
    assert len(pages[1]) == 35
    params = fake.params_for("/repos/o/r/issues")
    assert params[0]["page"] == 1
    assert params[1]["page"] == 2
    assert params[0]["state"] == "all"
    assert params[0]["sort"] == "updated"
    assert params[0]["direction"] == "asc"
    assert params[0]["per_page"] == 100


def test_get_issues_stops_on_empty_page():
    fake = FakeHttpClient().add("GET", "/repos/o/r/issues", FakeResponse(json_data=[]))
    client = GitHubClient("tok", client=HttpClient(fake))
    assert [p for p in client.get_issues("o", "r")] == []
