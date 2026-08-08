"""Unit tests for GitHub record normalization (spec §26)."""

from datetime import UTC, datetime

from pdw.connectors.github import GitHubConnector, Repo

REPO_JSON = {
    "id": 12345,
    "name": "personal-data-warehouse",
    "owner": {"login": "gvleverett"},
    "full_name": "gvleverett/personal-data-warehouse",
    "language": "Python",
    "created_at": "2024-01-15T10:30:00Z",
    "archived": False,
}

COMMIT_JSON = {
    "sha": "abc123def456",
    "commit": {
        "author": {
            "name": "Grace Leverett",
            "email": "grace@example.com",
            "date": "2024-06-01T12:00:00Z",
        },
        "message": "feat: add ingestion scaffold",
    },
}


def test_normalize_repo():
    repo = GitHubConnector._normalize_repo(REPO_JSON)
    assert repo.source_id == "gvleverett/personal-data-warehouse"
    assert repo.github_repository_id == 12345
    assert repo.owner == "gvleverett"
    assert repo.language == "Python"
    assert repo.archived is False
    assert repo.created_at == datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
    assert repo.raw_payload is REPO_JSON  # original API JSON preserved (spec §8)


def test_normalize_repo_null_language():
    repo = GitHubConnector._normalize_repo({**REPO_JSON, "language": None})
    assert repo.language is None


def test_normalize_commit():
    repo = Repo(
        source_id="gvleverett/personal-data-warehouse",
        github_repository_id=12345,
        name="personal-data-warehouse",
        owner="gvleverett",
        full_name="gvleverett/personal-data-warehouse",
        language="Python",
        created_at=datetime(2024, 1, 15, tzinfo=UTC),
        archived=False,
    )
    commit = GitHubConnector._normalize_commit(repo, COMMIT_JSON)
    assert commit.source_id == "gvleverett/personal-data-warehouse:abc123def456"
    assert commit.repository_source_id == repo.source_id
    assert commit.commit_sha == "abc123def456"
    assert commit.author_name == "Grace Leverett"
    assert commit.author_email == "grace@example.com"
    assert commit.committed_at == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    # list-commits does not return stats -> NULL (user-confirmed decision)
    assert commit.additions is None
    assert commit.deletions is None
    assert commit.message == "feat: add ingestion scaffold"
    assert commit.raw_payload is COMMIT_JSON