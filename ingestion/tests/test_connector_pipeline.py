"""Integration tests: fake HTTP -> real PostgreSQL (spec §12, §13, §25, §26).

These exercise the full runner path (fetch -> load -> checkpoint -> audit) with a
fake HTTP client but a real database, via the ``clean_db`` fixture.
"""

from __future__ import annotations

import types

import psycopg
from click.testing import CliRunner

from pdw.connectors.base import HttpClient
from pdw.connectors.calendar import CalendarClient, CalendarConnector
from pdw.connectors.github import GitHubClient, GitHubConnector
from pdw.pipeline.runner import run_calendar, run_github
from tests.fakes import FakeHttpClient, FakeResponse

# --- GitHub fixtures --------------------------------------------------------


def _repo_json(full_name: str, repo_id: int) -> dict:
    owner, name = full_name.split("/")
    return {
        "id": repo_id,
        "name": name,
        "owner": {"login": owner},
        "full_name": full_name,
        "language": "Python",
        "created_at": "2024-01-01T00:00:00Z",
        "archived": False,
    }


def _commit_json(sha: str, iso: str, message: str = "m") -> dict:
    return {
        "sha": sha,
        "commit": {
            "author": {"name": "Grace", "email": "g@e", "date": iso},
            "message": message,
        },
    }


def _github_fake(
    repos: list[dict], commits_by_repo: dict[str, list[dict]]
) -> FakeHttpClient:
    fake = FakeHttpClient()
    fake.add("GET", "/user/repos", FakeResponse(json_data=repos))
    for full_name, commits in commits_by_repo.items():
        owner, name = full_name.split("/")
        fake.add(
            "GET", f"/repos/{owner}/{name}/commits",
            FakeResponse(json_data=commits),
        )
    return fake


def _connector(fake: FakeHttpClient) -> GitHubConnector:
    return GitHubConnector(GitHubClient("tok", client=HttpClient(fake)))


def _count(dsn: str, table: str, where: str = "") -> int:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table} {where}")
            return cur.fetchone()[0]


# --- GitHub integration tests ----------------------------------------------


def test_github_loads_raw(clean_db: str):
    repos = [_repo_json("gvleverett/repo-a", 1), _repo_json("gvleverett/repo-b", 2)]
    commits = {
        "gvleverett/repo-a": [_commit_json("a1", "2024-06-01T00:00:00Z")],
        "gvleverett/repo-b": [_commit_json("b1", "2024-06-02T00:00:00Z")],
    }
    summary = run_github(_connector(_github_fake(repos, commits)), url=clean_db)

    assert summary.status == "success"
    assert summary.records_failed == 0
    assert _count(clean_db, "raw_github_repositories", "WHERE source='github'") == 2
    assert _count(clean_db, "raw_github_commits", "WHERE source='github'") == 2
    # one successful audit row
    assert _count(
        clean_db, "pipeline_runs", "WHERE source='github' AND status='success'"
    ) == 1
    # per-repo cursors written
    assert _count(clean_db, "sync_state", "WHERE connector='github'") == 2


def test_github_idempotent(clean_db: str):
    repos = [_repo_json("gvleverett/repo-a", 1)]
    commits = {"gvleverett/repo-a": [_commit_json("a1", "2024-06-01T00:00:00Z")]}
    fake1 = _github_fake(repos, commits)
    first = run_github(_connector(fake1), url=clean_db)
    assert first.records_inserted == 2  # 1 repo + 1 commit

    fake2 = _github_fake(repos, commits)
    second = run_github(_connector(fake2), url=clean_db)
    assert second.records_inserted == 0
    assert second.records_updated == 2
    assert _count(clean_db, "raw_github_commits") == 1  # no duplication


def test_github_incremental_cursor(clean_db: str):
    repos = [_repo_json("gvleverett/repo-a", 1)]
    # Run 1: two commits, the newer at 2024-06-05.
    commits1 = {"gvleverett/repo-a": [
        _commit_json("a1", "2024-06-01T00:00:00Z"),
        _commit_json("a2", "2024-06-05T00:00:00Z"),
    ]}
    run_github(_connector(_github_fake(repos, commits1)), url=clean_db)

    # The cursor for repo-a is the max committed_at (2024-06-05).
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_cursor FROM sync_state "
                "WHERE connector='github' AND entity_key='gvleverett/repo-a'"
            )
            cursor = cur.fetchone()[0]
    assert cursor.startswith("2024-06-05")

    # Run 2: one new commit; the runner must request since=cursor.
    commits2 = {"gvleverett/repo-a": [_commit_json("a3", "2024-06-10T00:00:00Z")]}
    fake2 = _github_fake(repos, commits2)
    second = run_github(_connector(fake2), url=clean_db)

    assert second.records_inserted == 1  # only the new commit
    params = fake2.params_for("/repos/gvleverett/repo-a/commits")[0]
    assert params["since"].startswith("2024-06-05")
    assert _count(clean_db, "raw_github_commits") == 3


def test_github_partial_failure(clean_db: str):
    """A 404 on one repo's commits -> partial run, other repo still syncs."""
    repos = [_repo_json("gvleverett/repo-a", 1), _repo_json("gvleverett/repo-b", 2)]
    fake = FakeHttpClient()
    fake.add("GET", "/user/repos", FakeResponse(json_data=repos))
    fake.add("GET", "/repos/gvleverett/repo-a/commits",
             FakeResponse(json_data=[_commit_json("a1", "2024-06-01T00:00:00Z")]))
    fake.add("GET", "/repos/gvleverett/repo-b/commits",
             FakeResponse(status_code=404, json_data={}))  # repo-b 404s

    summary = run_github(_connector(fake), url=clean_db)

    assert summary.status == "partial"
    assert summary.records_failed == 1
    # repo-a cursor set, repo-b cursor absent
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT entity_key FROM sync_state WHERE connector='github'"
            )
            keys = {r[0] for r in cur.fetchall()}
    assert "gvleverett/repo-a" in keys
    assert "gvleverett/repo-b" not in keys
    assert _count(clean_db, "raw_github_commits") == 1  # only repo-a's commit


# --- Calendar integration tests --------------------------------------------


def _cal_fake(events_pages: list[dict]) -> FakeHttpClient:
    fake = FakeHttpClient()
    for page in events_pages:
        fake.add("GET", "/calendars/primary/events", FakeResponse(json_data=page))
    return fake


def _cal_connector(fake: FakeHttpClient) -> CalendarConnector:
    return CalendarConnector(
        CalendarClient("access", http=HttpClient(fake)), calendar_id="primary"
    )


def test_calendar_loads_raw(clean_db: str):
    events = {
        "items": [
            {  # timed event
                "id": "evt1", "status": "confirmed", "summary": "Weekly sync",
                "start": {"dateTime": "2024-06-01T09:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": "2024-06-01T09:30:00Z", "timeZone": "UTC"},
                "attendees": [{"email": "a@x"}, {"email": "b@x"}],
            },
            {  # all-day event
                "id": "evt2", "status": "confirmed", "summary": "OOO",
                "start": {"date": "2024-06-10", "timeZone": "UTC"},
                "end": {"date": "2024-06-11", "timeZone": "UTC"},
            },
        ]
    }
    summary = run_calendar(_cal_connector(_cal_fake([events])), url=clean_db)

    assert summary.status == "success"
    assert _count(clean_db, "raw_calendar_events", "WHERE source='calendar'") == 2
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, category, start_at, attendees_count "
                "FROM raw_calendar_events WHERE source_id='evt1'"
            )
            title, category, start_at, attendees = cur.fetchone()
            assert title == "Weekly sync"
            assert category == "meeting"
            assert attendees == 2
            # all-day event stored at midnight UTC
            cur.execute("SELECT start_at FROM raw_calendar_events WHERE source_id='evt2'")
            assert str(cur.fetchone()[0]).startswith("2024-06-10")


def test_calendar_incremental_upserts_cancellations(clean_db: str):
    # Run 1: backfill (no cursor) loads a confirmed event.
    run_calendar(
        _cal_connector(_cal_fake([{"items": [
            {"id": "evt1", "status": "confirmed", "summary": "Weekly sync",
             "start": {"dateTime": "2024-06-01T09:00:00Z", "timeZone": "UTC"},
             "end": {"dateTime": "2024-06-01T09:30:00Z", "timeZone": "UTC"}},
        ]}])),
        url=clean_db,
    )

    # Run 2: incremental (cursor exists) returns the same id now cancelled.
    run_calendar(
        _cal_connector(_cal_fake([{"items": [
            {"id": "evt1", "status": "cancelled"},
        ]}])),
        url=clean_db,
    )

    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM raw_calendar_events WHERE source_id='evt1'"
            )
            assert cur.fetchone()[0] == "cancelled"
            # cursor advanced (calendar connector key)
            cur.execute(
                "SELECT last_cursor FROM sync_state "
                "WHERE connector='calendar' AND entity_key='primary'"
            )
            assert cur.fetchone()[0] is not None
    assert _count(clean_db, "raw_calendar_events") == 1  # upserted, not duplicated


# --- CLI credential guard (spec §7) ----------------------------------------


def test_github_credentials_missing(monkeypatch):
    """`pdw sync github` with no token gives a clear error naming the env var."""
    import pdw.cli as cli

    monkeypatch.setattr(
        cli, "get_settings",
        lambda: types.SimpleNamespace(github_token=None),
    )
    result = CliRunner().invoke(cli.main, ["sync", "github"])
    assert result.exit_code != 0
    assert "GITHUB_TOKEN" in result.output