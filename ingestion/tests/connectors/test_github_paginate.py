"""Unit tests for GitHub pagination (spec §26)."""

from pdw.connectors.base import HttpClient
from pdw.connectors.github import GitHubClient
from tests.fakes import FakeHttpClient, FakeResponse


def _repo(i: int) -> dict:
    return {
        "id": i,
        "name": f"repo-{i}",
        "owner": {"login": "gvleverett"},
        "full_name": f"gvleverett/repo-{i}",
        "language": "Python",
        "created_at": "2024-01-01T00:00:00Z",
        "archived": False,
    }


def test_get_repos_paginates_until_short_page():
    fake = FakeHttpClient()
    page1 = [_repo(i) for i in range(100)]
    page2 = [_repo(i) for i in range(100, 135)]  # short page -> stop
    fake.add("GET", "/user/repos", FakeResponse(json_data=page1),
             FakeResponse(json_data=page2))
    client = GitHubClient("tok", client=HttpClient(fake))

    pages = [p for p in client.get_repos()]

    assert len(pages) == 2
    assert len(pages[0]) == 100
    assert len(pages[1]) == 35
    # page param increments
    params = fake.params_for("/user/repos")
    assert params[0]["page"] == 1
    assert params[1]["page"] == 2


def test_get_repos_stops_on_empty_page():
    fake = FakeHttpClient().add("GET", "/user/repos", FakeResponse(json_data=[]))
    client = GitHubClient("tok", client=HttpClient(fake))

    pages = [p for p in client.get_repos()]
    assert pages == []


def test_get_commits_paginates():
    fake = FakeHttpClient()
    page1 = [{"sha": f"sha-{i}", "commit": {"author": {"name": "a", "email": "e",
        "date": "2024-06-01T00:00:00Z"}, "message": "m"}} for i in range(100)]
    page2 = [{"sha": f"sha-{i}", "commit": {"author": {"name": "a", "email": "e",
        "date": "2024-06-02T00:00:00Z"}, "message": "m"}} for i in range(100, 105)]
    fake.add("GET", "/repos/gvleverett/repo/commits",
             FakeResponse(json_data=page1), FakeResponse(json_data=page2))
    client = GitHubClient("tok", client=HttpClient(fake))

    pages = [p for p in client.get_commits("gvleverett", "repo")]
    assert len(pages) == 2
    assert len(pages[1]) == 5