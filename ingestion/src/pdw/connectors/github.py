"""GitHub connector (spec §6, §25).

Wraps the GitHub REST API and normalizes repositories + commits into the
shared ``pdw.models`` records. Commits are fetched per-repository with a
``since`` cursor (ISO-8601) for incremental syncs.

Notes from the official docs:
  * ``GET /user/repos`` — list the authenticated user's repos (per_page=100,
    paginate by incrementing ``page`` until a page is short/empty).
  * ``GET /repos/{owner}/{repo}/commits?since=…`` — commits after a timestamp
    (per_page=100). **Does not** return additions/deletions, so those are NULL.
  * A **409** on commits means the repo is empty (Git not initialized) — treated
    as an empty list, not an error.
  * Rate limit: 5000 req/hr for authenticated requests; check
    ``X-RateLimit-Remaining``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import httpx

from ..models import Commit, Issue, PullRequest, Repo
from .base import ApiError, HttpClient, MalformedRecordError

API_ROOT = "https://api.github.com"
PER_PAGE = 100


def _parse_dt(value: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp (e.g. 2024-01-15T10:30:00Z)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubClient:
    """Thin GitHub REST API client (httpx wrapper, injectable for tests)."""

    def __init__(self, token: str, *, client: HttpClient | None = None) -> None:
        if not token:
            raise ValueError("GITHUB_TOKEN is required (spec §7)")
        self._token = token
        self._http = client or HttpClient(
            httpx.Client(
                base_url=API_ROOT,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        )

    def get_repos(self) -> Iterator[list[dict]]:
        """Yield pages of repositories for the authenticated user."""
        page = 1
        while True:
            data = self._http.get(
                f"{API_ROOT}/user/repos",
                per_page=PER_PAGE,
                page=page,
                sort="pushed",
                direction="desc",
            ).json()
            if not data:
                return
            yield data
            if len(data) < PER_PAGE:
                return
            page += 1

    def get_commits(
        self, owner: str, repo: str, since: datetime | None = None
    ) -> Iterator[list[dict]]:
        """Yield pages of commits for a repository since a cursor.

        A 409 (empty repo) yields a single empty page rather than raising.
        """
        params: dict = {"per_page": PER_PAGE}
        if since is not None:
            params["since"] = since.isoformat()
        path = f"{API_ROOT}/repos/{owner}/{repo}/commits"
        try:
            page = 1
            while True:
                params["page"] = page
                data = self._http.get(path, **params).json()
                if not data:
                    return
                yield data
                if len(data) < PER_PAGE:
                    return
                page += 1
        except ApiError as exc:
            if exc.status_code == 409:
                return  # empty repo — not an error
            raise

    def get_issues(
        self, owner: str, repo: str, since: datetime | None = None
    ) -> Iterator[list[dict]]:
        """Yield pages of issues **and** pull requests for a repository since a
        cursor.

        The GitHub issues endpoint returns PRs too (every PR is an issue); the
        connector splits them on the ``pull_request`` key. ``since`` filters to
        items updated at or after the cursor (incremental sync). ``state=all``
        so closed items are returned for backfill.
        """
        params: dict = {
            "per_page": PER_PAGE,
            "state": "all",
            "sort": "updated",
            "direction": "asc",
        }
        if since is not None:
            params["since"] = since.isoformat()
        path = f"{API_ROOT}/repos/{owner}/{repo}/issues"
        page = 1
        while True:
            params["page"] = page
            data = self._http.get(path, **params).json()
            if not data:
                return
            yield data
            if len(data) < PER_PAGE:
                return
            page += 1


class GitHubConnector:
    """Normalizes GitHub API responses into shared records."""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def fetch_repos(self) -> list[Repo]:
        repos: list[Repo] = []
        for page in self._client.get_repos():
            for raw in page:
                try:
                    repos.append(self._normalize_repo(raw))
                except (KeyError, TypeError) as exc:
                    raise MalformedRecordError(
                        f"could not normalize repo: {exc}"
                    ) from exc
        return repos

    def fetch_commits(self, repo: Repo, since: datetime | None = None) -> list[Commit]:
        commits: list[Commit] = []
        for page in self._client.get_commits(repo.owner, repo.name, since=since):
            for raw in page:
                try:
                    commits.append(self._normalize_commit(repo, raw))
                except (KeyError, TypeError) as exc:
                    raise MalformedRecordError(
                        f"could not normalize commit in {repo.full_name}: {exc}"
                    ) from exc
        return commits

    @staticmethod
    def _normalize_repo(raw: dict) -> Repo:
        return Repo(
            source_id=raw["full_name"],
            github_repository_id=raw["id"],
            name=raw["name"],
            owner=raw["owner"]["login"],
            full_name=raw["full_name"],
            language=raw.get("language"),
            created_at=_parse_dt(raw["created_at"]),
            archived=raw.get("archived", False),
            raw_payload=raw,
        )

    @staticmethod
    def _normalize_commit(repo: Repo, raw: dict) -> Commit:
        author = raw["commit"]["author"]
        return Commit(
            source_id=f"{repo.full_name}:{raw['sha']}",
            repository_source_id=repo.source_id,
            commit_sha=raw["sha"],
            author_name=author["name"],
            author_email=author.get("email") or "",
            committed_at=_parse_dt(author["date"]),
            additions=None,  # list-commits does not return stats
            deletions=None,
            message=raw["commit"]["message"],
            raw_payload=raw,
        )


class GitHubIssuesConnector:
    """Normalizes the GitHub issues endpoint into Issues + PullRequests.

    The ``GET /repos/{owner}/{repo}/issues`` endpoint returns both issues and
    PRs (every PR is an issue). This connector fetches the user's repos (reusing
    ``GitHubConnector`` so repo normalization isn't duplicated), then per repo
    fetches issues/PRs with a ``since`` cursor and splits each item on the
    ``pull_request`` key.
    """

    def __init__(self, client: GitHubClient) -> None:
        self._client = client
        self._repo_connector = GitHubConnector(client)

    def fetch_repos(self) -> list[Repo]:
        return self._repo_connector.fetch_repos()

    def fetch_issues_prs(
        self, repo: Repo, since: datetime | None = None
    ) -> tuple[list[Issue], list[PullRequest]]:
        """Fetch issues + PRs for a repo since a cursor; split into two lists."""
        issues: list[Issue] = []
        prs: list[PullRequest] = []
        for page in self._client.get_issues(repo.owner, repo.name, since=since):
            for raw in page:
                try:
                    if raw.get("pull_request") is not None:
                        prs.append(self._normalize_pull_request(repo, raw))
                    else:
                        issues.append(self._normalize_issue(repo, raw))
                except (KeyError, TypeError) as exc:
                    raise MalformedRecordError(
                        f"could not normalize issue/PR in {repo.full_name}: {exc}"
                    ) from exc
        return issues, prs

    @staticmethod
    def _normalize_issue(repo: Repo, raw: dict) -> Issue:
        return Issue(
            source_id=raw["node_id"],
            repository_source_id=repo.source_id,
            number=raw["number"],
            title=raw["title"],
            state=raw["state"],
            state_reason=raw.get("state_reason"),
            author=(raw.get("user") or {}).get("login"),
            created_at=_parse_dt(raw["created_at"]),
            updated_at=_parse_dt(raw["updated_at"]),
            closed_at=_parse_dt(raw["closed_at"]) if raw.get("closed_at") else None,
            comments_count=raw.get("comments", 0),
            raw_payload=raw,
        )

    @staticmethod
    def _normalize_pull_request(repo: Repo, raw: dict) -> PullRequest:
        pr = raw["pull_request"]
        return PullRequest(
            source_id=raw["node_id"],
            repository_source_id=repo.source_id,
            number=raw["number"],
            title=raw["title"],
            state=raw["state"],
            author=(raw.get("user") or {}).get("login"),
            created_at=_parse_dt(raw["created_at"]),
            updated_at=_parse_dt(raw["updated_at"]),
            closed_at=_parse_dt(raw["closed_at"]) if raw.get("closed_at") else None,
            merged_at=_parse_dt(pr["merged_at"]) if pr.get("merged_at") else None,
            is_draft=raw.get("draft", False),
            comments_count=raw.get("comments", 0),
            raw_payload=raw,
        )
