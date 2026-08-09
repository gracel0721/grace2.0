"""Unit tests for GitHub PR/issue record normalization (spec §6, §26).

The ``GET /repos/{owner}/{repo}/issues`` endpoint returns both issues and pull
requests; every PR is an issue that carries a ``pull_request`` sub-object. The
connector splits on that key. Note: the issues endpoint's ``pull_request``
sub-object only carries URLs — ``merged_at`` is not available there (NULL, like
the commits endpoint omits additions/deletions). ``draft`` is a top-level field.
"""

from datetime import UTC, datetime

from pdw.connectors.base import HttpClient
from pdw.connectors.github import GitHubClient, GitHubIssuesConnector, Repo
from tests.fakes import FakeHttpClient, FakeResponse

REPO = Repo(
    source_id="gvleverett/personal-data-warehouse",
    github_repository_id=12345,
    name="personal-data-warehouse",
    owner="gvleverett",
    full_name="gvleverett/personal-data-warehouse",
    language="Python",
    created_at=datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
    archived=False,
)


def _issue_json(
    number=1,
    node_id="I_kw",
    iso="2024-06-01T12:00:00Z",
    state="open",
    state_reason="completed",
    closed=False,
):
    return {
        "node_id": node_id,
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "state_reason": state_reason,
        "user": {"login": "gvleverett"},
        "created_at": iso,
        "updated_at": iso,
        "closed_at": iso if closed else None,
        "comments": 4,
    }


def _pr_json(
    number=2,
    node_id="PR_kw",
    iso="2024-06-02T12:00:00Z",
    state="open",
    draft=False,
    closed=False,
):
    return {
        "node_id": node_id,
        "number": number,
        "title": f"PR {number}",
        "state": state,
        "user": {"login": "gvleverett"},
        "created_at": iso,
        "updated_at": iso,
        "closed_at": iso if closed else None,
        "draft": draft,
        "comments": 7,
        # The issues endpoint's `pull_request` sub-object only carries URLs;
        # `merged_at` is not available here (NULL, like additions/deletions).
        "pull_request": {
            "url": "https://api.github.com/repos/gvleverett/pdw/pulls/2",
            "html_url": "https://github.com/gvleverett/pdw/pull/2",
        },
    }


def test_normalize_issue():
    raw = _issue_json(
        number=42,
        node_id="I_1",
        iso="2024-06-01T12:00:00Z",
        state="closed",
        state_reason="completed",
        closed=True,
    )
    issue = GitHubIssuesConnector._normalize_issue(REPO, raw)
    assert issue.source_id == "I_1"
    assert issue.repository_source_id == REPO.source_id
    assert issue.number == 42
    assert issue.title == "Issue 42"
    assert issue.state == "closed"
    assert issue.state_reason == "completed"
    assert issue.author == "gvleverett"
    assert issue.created_at == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    assert issue.updated_at == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    assert issue.closed_at == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    assert issue.comments_count == 4
    assert issue.raw_payload is raw  # original API JSON preserved (spec §8)


def test_normalize_issue_null_state_reason():
    issue = GitHubIssuesConnector._normalize_issue(REPO, _issue_json(state_reason=None))
    assert issue.state_reason is None


def test_normalize_issue_open_has_no_closed_at():
    issue = GitHubIssuesConnector._normalize_issue(REPO, _issue_json(closed=False))
    assert issue.closed_at is None


def test_normalize_issue_missing_user():
    raw = _issue_json()
    del raw["user"]
    issue = GitHubIssuesConnector._normalize_issue(REPO, raw)
    assert issue.author is None


def test_normalize_pull_request():
    raw = _pr_json(
        number=7,
        node_id="PR_1",
        iso="2024-06-02T12:00:00Z",
        state="closed",
        draft=True,
        closed=True,
    )
    pr = GitHubIssuesConnector._normalize_pull_request(REPO, raw)
    assert pr.source_id == "PR_1"
    assert pr.repository_source_id == REPO.source_id
    assert pr.number == 7
    assert pr.title == "PR 7"
    assert pr.state == "closed"
    assert pr.author == "gvleverett"
    assert pr.created_at == datetime(2024, 6, 2, 12, 0, tzinfo=UTC)
    assert pr.updated_at == datetime(2024, 6, 2, 12, 0, tzinfo=UTC)
    assert pr.closed_at == datetime(2024, 6, 2, 12, 0, tzinfo=UTC)
    # merged_at is not available from the issues endpoint -> NULL.
    assert pr.merged_at is None
    assert pr.is_draft is True
    assert pr.comments_count == 7
    assert pr.raw_payload is raw


def test_normalize_pull_request_merged_when_provided():
    """If a `merged_at` is present in the pull_request sub-object it is parsed
    (defensive — the issues endpoint does not normally send it)."""
    raw = _pr_json(node_id="PR_2", iso="2024-06-03T12:00:00Z")
    raw["pull_request"]["merged_at"] = "2024-06-03T12:30:00Z"
    pr = GitHubIssuesConnector._normalize_pull_request(REPO, raw)
    assert pr.merged_at == datetime(2024, 6, 3, 12, 30, tzinfo=UTC)


def test_normalize_pull_request_not_draft_by_default():
    pr = GitHubIssuesConnector._normalize_pull_request(REPO, _pr_json(draft=False))
    assert pr.is_draft is False


def test_fetch_issues_prs_splits_on_pull_request_key():
    """The connector routes each item to issues or PRs based on the
    `pull_request` key."""
    page = [
        _issue_json(number=1, node_id="I_1"),
        _pr_json(number=2, node_id="PR_1"),
        _issue_json(number=3, node_id="I_2"),
    ]
    fake = FakeHttpClient().add(
        "GET",
        "/repos/gvleverett/personal-data-warehouse/issues",
        FakeResponse(json_data=page),
    )
    connector = GitHubIssuesConnector(GitHubClient("tok", client=HttpClient(fake)))

    issues, prs = connector.fetch_issues_prs(REPO)

    assert [i.source_id for i in issues] == ["I_1", "I_2"]
    assert [p.source_id for p in prs] == ["PR_1"]
