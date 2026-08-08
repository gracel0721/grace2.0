"""Unit tests for GitHub error handling (spec §25, §26)."""

import httpx
import pytest

from pdw.connectors.base import (
    ApiError,
    AuthError,
    HttpClient,
    NetworkError,
    RateLimitError,
)
from pdw.connectors.github import GitHubClient
from tests.fakes import FakeHttpClient, FakeResponse


def test_401_raises_auth_error():
    fake = FakeHttpClient().add(
        "GET", "/user/repos", FakeResponse(status_code=401, json_data={})
    )
    client = GitHubClient("tok", client=HttpClient(fake))
    try:
        list(client.get_repos())
    except AuthError:
        pass
    else:
        raise AssertionError("expected AuthError for 401")


def test_rate_limit_exhausted_raises_rate_limit_error():
    fake = FakeHttpClient().add(
        "GET", "/user/repos",
        FakeResponse(
            status_code=403, json_data={},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
        ),
    )
    client = GitHubClient("tok", client=HttpClient(fake))
    try:
        list(client.get_repos())
    except RateLimitError:
        pass
    else:
        raise AssertionError("expected RateLimitError when remaining=0")


def test_409_empty_repo_yields_no_commits():
    """A 409 on commits means the repo is empty -> not an error (spec §25)."""
    fake = FakeHttpClient().add(
        "GET", "/repos/o/r/commits", FakeResponse(status_code=409, json_data={})
    )
    client = GitHubClient("tok", client=HttpClient(fake))
    pages = list(client.get_commits("o", "r"))
    assert pages == []  # empty repo, no error raised


def test_404_on_commits_raises_api_error():
    fake = FakeHttpClient().add(
        "GET", "/repos/o/r/commits", FakeResponse(status_code=404, json_data={})
    )
    client = GitHubClient("tok", client=HttpClient(fake))
    try:
        list(client.get_commits("o", "r"))
    except ApiError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected ApiError for 404")


def test_network_error_retried_then_raised():
    """A transport failure is retried once, then surfaces as a NetworkError."""
    fake = FakeHttpClient().add(
        "GET", "/user/repos",
        httpx.ConnectError("boom"),  # transport failure
        httpx.ConnectError("boom"),  # retry also fails
    )
    client = GitHubClient("tok", client=HttpClient(fake, max_retries=1))

    with pytest.raises(NetworkError):
        list(client.get_repos())