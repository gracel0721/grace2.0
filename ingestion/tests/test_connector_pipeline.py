"""Integration tests: fake HTTP -> real PostgreSQL (spec §12, §13, §25, §26).

These exercise the full runner path (fetch -> load -> checkpoint -> audit) with a
fake HTTP client but a real database, via the ``clean_db`` fixture.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime

import psycopg
from click.testing import CliRunner

from pdw.connectors.base import HttpClient
from pdw.connectors.calendar import CalendarClient, CalendarConnector
from pdw.connectors.github import GitHubClient, GitHubConnector, GitHubIssuesConnector
from pdw.connectors.gmail import GmailClient, GmailConnector
from pdw.connectors.spotify import SpotifyClient, SpotifyConnector
from pdw.pipeline.runner import (
    run_calendar,
    run_github,
    run_github_issues,
    run_gmail,
    run_spotify,
)
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
            "GET",
            f"/repos/{owner}/{name}/commits",
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
    assert (
        _count(clean_db, "pipeline_runs", "WHERE source='github' AND status='success'")
        == 1
    )
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
    commits1 = {
        "gvleverett/repo-a": [
            _commit_json("a1", "2024-06-01T00:00:00Z"),
            _commit_json("a2", "2024-06-05T00:00:00Z"),
        ]
    }
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
    fake.add(
        "GET",
        "/repos/gvleverett/repo-a/commits",
        FakeResponse(json_data=[_commit_json("a1", "2024-06-01T00:00:00Z")]),
    )
    fake.add(
        "GET",
        "/repos/gvleverett/repo-b/commits",
        FakeResponse(status_code=404, json_data={}),
    )  # repo-b 404s

    summary = run_github(_connector(fake), url=clean_db)

    assert summary.status == "partial"
    assert summary.records_failed == 1
    # repo-a cursor set, repo-b cursor absent
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT entity_key FROM sync_state WHERE connector='github'")
            keys = {r[0] for r in cur.fetchall()}
    assert "gvleverett/repo-a" in keys
    assert "gvleverett/repo-b" not in keys
    assert _count(clean_db, "raw_github_commits") == 1  # only repo-a's commit


# --- GitHub issues + PRs integration tests ---------------------------------


def _gh_issue_json(
    number, node_id, iso, state="open", state_reason="completed", closed=False
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


def _gh_pr_json(number, node_id, iso, state="open", draft=False, closed=False):
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
        # `merged_at` is not available from this endpoint (NULL).
        "pull_request": {
            "url": "https://api.github.com/repos/gvleverett/pdw/pulls/2",
            "html_url": "https://github.com/gvleverett/pdw/pull/2",
        },
    }


def _issues_fake(repos, items_by_repo):
    fake = FakeHttpClient()
    fake.add("GET", "/user/repos", FakeResponse(json_data=repos))
    for full_name, items in items_by_repo.items():
        owner, name = full_name.split("/")
        fake.add(
            "GET",
            f"/repos/{owner}/{name}/issues",
            FakeResponse(json_data=items),
        )
    return fake


def _issues_connector(fake):
    return GitHubIssuesConnector(GitHubClient("tok", client=HttpClient(fake)))


def test_github_issues_loads_raw(clean_db):
    repos = [_repo_json("gvleverett/repo-a", 1), _repo_json("gvleverett/repo-b", 2)]
    items = {
        "gvleverett/repo-a": [
            _gh_issue_json(1, "I_1", "2024-06-01T00:00:00Z"),
            _gh_pr_json(2, "PR_1", "2024-06-02T00:00:00Z"),
        ],
        "gvleverett/repo-b": [_gh_issue_json(3, "I_2", "2024-06-03T00:00:00Z")],
    }
    summary = run_github_issues(
        _issues_connector(_issues_fake(repos, items)), url=clean_db
    )

    assert summary.status == "success"
    assert summary.records_failed == 0
    assert _count(clean_db, "raw_github_repositories", "WHERE source='github'") == 2
    assert _count(clean_db, "raw_github_issues", "WHERE source='github'") == 2
    assert _count(clean_db, "raw_github_pull_requests", "WHERE source='github'") == 1
    assert (
        _count(clean_db, "pipeline_runs", "WHERE source='github' AND status='success'")
        == 1
    )
    # per-repo cursors under the github_issues connector
    assert _count(clean_db, "sync_state", "WHERE connector='github_issues'") == 2


def test_github_issues_idempotent(clean_db):
    repos = [_repo_json("gvleverett/repo-a", 1)]
    items = {
        "gvleverett/repo-a": [
            _gh_issue_json(1, "I_1", "2024-06-01T00:00:00Z"),
            _gh_pr_json(2, "PR_1", "2024-06-02T00:00:00Z"),
        ]
    }
    first = run_github_issues(_issues_connector(_issues_fake(repos, items)), url=clean_db)
    assert first.records_inserted == 3  # 1 repo + 1 issue + 1 PR

    second = run_github_issues(
        _issues_connector(_issues_fake(repos, items)), url=clean_db
    )
    assert second.records_inserted == 0
    assert second.records_updated == 3
    assert _count(clean_db, "raw_github_issues") == 1
    assert _count(clean_db, "raw_github_pull_requests") == 1


def test_github_issues_incremental_cursor(clean_db):
    repos = [_repo_json("gvleverett/repo-a", 1)]
    # Run 1: one issue, updated at 2024-06-05.
    items1 = {
        "gvleverett/repo-a": [
            _gh_issue_json(1, "I_1", "2024-06-05T00:00:00Z"),
        ]
    }
    run_github_issues(_issues_connector(_issues_fake(repos, items1)), url=clean_db)

    # The cursor for repo-a is the max updated_at (2024-06-05).
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_cursor FROM sync_state "
                "WHERE connector='github_issues' AND entity_key='gvleverett/repo-a'"
            )
            cursor = cur.fetchone()[0]
    assert cursor.startswith("2024-06-05")

    # Run 2: one new issue; the runner must request since=cursor.
    items2 = {
        "gvleverett/repo-a": [
            _gh_issue_json(2, "I_2", "2024-06-10T00:00:00Z"),
        ]
    }
    fake2 = _issues_fake(repos, items2)
    second = run_github_issues(_issues_connector(fake2), url=clean_db)

    assert second.records_inserted == 1  # only the new issue (repo is an update)
    params = fake2.params_for("/repos/gvleverett/repo-a/issues")[0]
    assert params["since"].startswith("2024-06-05")
    assert _count(clean_db, "raw_github_issues") == 2


def test_github_issues_partial_failure(clean_db):
    """A 404 on one repo's issues -> partial run, other repo still syncs."""
    repos = [_repo_json("gvleverett/repo-a", 1), _repo_json("gvleverett/repo-b", 2)]
    fake = FakeHttpClient()
    fake.add("GET", "/user/repos", FakeResponse(json_data=repos))
    fake.add(
        "GET",
        "/repos/gvleverett/repo-a/issues",
        FakeResponse(json_data=[_gh_issue_json(1, "I_1", "2024-06-01T00:00:00Z")]),
    )
    fake.add(
        "GET",
        "/repos/gvleverett/repo-b/issues",
        FakeResponse(status_code=404, json_data={}),
    )  # repo-b 404s

    summary = run_github_issues(_issues_connector(fake), url=clean_db)

    assert summary.status == "partial"
    assert summary.records_failed == 1
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT entity_key FROM sync_state WHERE connector='github_issues'"
            )
            keys = {r[0] for r in cur.fetchall()}
    assert "gvleverett/repo-a" in keys
    assert "gvleverett/repo-b" not in keys
    assert _count(clean_db, "raw_github_issues") == 1  # only repo-a's issue


def test_github_issues_preserves_updated_at(clean_db):
    """The `updated_at` column must hold GitHub's value, not ingestion time,
    even after an upsert (regression guard for the double-assignment bug)."""
    repos = [_repo_json("gvleverett/repo-a", 1)]
    items = {
        "gvleverett/repo-a": [
            _gh_issue_json(1, "I_1", "2024-06-05T12:00:00Z", closed=True),
        ]
    }
    run_github_issues(_issues_connector(_issues_fake(repos, items)), url=clean_db)
    # re-run -> upsert (update path), which previously clobbered updated_at.
    run_github_issues(_issues_connector(_issues_fake(repos, items)), url=clean_db)

    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT updated_at FROM raw_github_issues WHERE source_id='I_1'")
            updated_at = cur.fetchone()[0]
    assert updated_at == datetime(2024, 6, 5, 12, 0, tzinfo=UTC)


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
                "id": "evt1",
                "status": "confirmed",
                "summary": "Weekly sync",
                "start": {"dateTime": "2024-06-01T09:00:00Z", "timeZone": "UTC"},
                "end": {"dateTime": "2024-06-01T09:30:00Z", "timeZone": "UTC"},
                "attendees": [{"email": "a@x"}, {"email": "b@x"}],
            },
            {  # all-day event
                "id": "evt2",
                "status": "confirmed",
                "summary": "OOO",
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
        _cal_connector(
            _cal_fake(
                [
                    {
                        "items": [
                            {
                                "id": "evt1",
                                "status": "confirmed",
                                "summary": "Weekly sync",
                                "start": {
                                    "dateTime": "2024-06-01T09:00:00Z",
                                    "timeZone": "UTC",
                                },
                                "end": {
                                    "dateTime": "2024-06-01T09:30:00Z",
                                    "timeZone": "UTC",
                                },
                            },
                        ]
                    }
                ]
            )
        ),
        url=clean_db,
    )

    # Run 2: incremental (cursor exists) returns the same id now cancelled.
    run_calendar(
        _cal_connector(
            _cal_fake(
                [
                    {
                        "items": [
                            {"id": "evt1", "status": "cancelled"},
                        ]
                    }
                ]
            )
        ),
        url=clean_db,
    )

    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM raw_calendar_events WHERE source_id='evt1'")
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
        cli,
        "get_settings",
        lambda: types.SimpleNamespace(github_token=None),
    )
    result = CliRunner().invoke(cli.main, ["sync", "github"])
    assert result.exit_code != 0
    assert "GITHUB_TOKEN" in result.output


# --- Gmail integration tests -----------------------------------------------


def _gmail_stub(mid, thread="t1"):
    return {"id": mid, "threadId": thread}


def _gmail_full(mid, internal, sender="Ada <ada@x>", subject="Hello", snippet="prev"):
    return {
        "id": mid,
        "threadId": "t1",
        "internalDate": internal,  # epoch ms string
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@x"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Tue, 04 Jun 2024 12:00:00 +0000"},
            ]
        },
    }


def _gmail_fake(stub_pages, fulls):
    """Build a fake: per-id GETs registered first (substring-route ordering)."""
    fake = FakeHttpClient()
    for mid, full in fulls.items():
        fake.add("GET", f"/users/me/messages/{mid}", FakeResponse(json_data=full))
    for page in stub_pages:
        fake.add("GET", "/users/me/messages", FakeResponse(json_data=page))
    return fake


def _gmail_connector(fake):
    return GmailConnector(GmailClient("access", http=HttpClient(fake)))


def test_gmail_loads_raw(clean_db: str):
    stubs = {"messages": [_gmail_stub("m0"), _gmail_stub("m1")]}
    fulls = {
        "m0": _gmail_full("m0", "1717588800000"),  # 2024-06-05T12:00:00Z
        "m1": _gmail_full("m1", "1717675200000"),  # 2024-06-06T12:00:00Z
    }
    summary = run_gmail(_gmail_connector(_gmail_fake([stubs], fulls)), url=clean_db)

    assert summary.status == "success"
    assert _count(clean_db, "raw_gmail_messages", "WHERE source='gmail'") == 2
    assert (
        _count(clean_db, "pipeline_runs", "WHERE source='gmail' AND status='success'")
        == 1
    )
    # cursor written under the gmail connector, single 'primary' entity
    assert _count(clean_db, "sync_state", "WHERE connector='gmail'") == 1
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sender, subject, date FROM raw_gmail_messages "
                "WHERE source_id='m0'"
            )
            sender, subject, date = cur.fetchone()
            assert sender == "Ada <ada@x>"
            assert subject == "Hello"
            assert date == datetime(2024, 6, 5, 12, 0, tzinfo=UTC)


def test_gmail_idempotent(clean_db: str):
    stubs = {"messages": [_gmail_stub("m0")]}
    fulls = {"m0": _gmail_full("m0", "1717588800000")}
    first = run_gmail(_gmail_connector(_gmail_fake([stubs], fulls)), url=clean_db)
    assert first.records_inserted == 1

    second = run_gmail(_gmail_connector(_gmail_fake([stubs], fulls)), url=clean_db)
    assert second.records_inserted == 0
    assert second.records_updated == 1
    assert _count(clean_db, "raw_gmail_messages") == 1  # no duplication


def test_gmail_incremental_cursor(clean_db: str):
    # Run 1: one message on 2024-06-05.
    stubs1 = {"messages": [_gmail_stub("m0")]}
    fulls1 = {"m0": _gmail_full("m0", "1717588800000")}
    run_gmail(_gmail_connector(_gmail_fake([stubs1], fulls1)), url=clean_db)

    # The cursor (primary) is the max message date = 2024-06-05.
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_cursor FROM sync_state "
                "WHERE connector='gmail' AND entity_key='primary'"
            )
            cursor = cur.fetchone()[0]
    assert cursor.startswith("2024-06-05")

    # Run 2: one new message; the runner must request q=after:2024/06/05.
    stubs2 = {"messages": [_gmail_stub("m1")]}
    fulls2 = {"m1": _gmail_full("m1", "1717675200000")}
    fake2 = _gmail_fake([stubs2], fulls2)
    second = run_gmail(_gmail_connector(fake2), url=clean_db)

    assert second.records_inserted == 1
    params = fake2.params_for("/users/me/messages")[0]
    assert params["q"] == "after:2024/06/05"
    assert _count(clean_db, "raw_gmail_messages") == 2


def test_gmail_metadata_only_no_body_stored(clean_db: str):
    """Regression guard (spec §23): raw_payload + columns hold only metadata,
    never a message body. A `body` field on the source JSON must not leak into
    any stored column, and the stored snippet is Gmail's preview, not the body."""
    stubs = {"messages": [_gmail_stub("m0")]}
    fulls = {
        "m0": {
            **_gmail_full("m0", "1717588800000", snippet="preview text"),
            # a body present in the upstream response (format=metadata omits it,
            # but guard against it ever being persisted if the format changes)
            "payload": {
                "headers": [{"name": "From", "value": "a@x"}],
                "body": {"data": "SECRET BODY CONTENT"},
            },
        }
    }
    run_gmail(_gmail_connector(_gmail_fake([stubs], fulls)), url=clean_db)

    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT snippet, raw_payload FROM raw_gmail_messages "
                "WHERE source_id='m0'"
            )
            snippet, payload = cur.fetchone()
            assert snippet == "preview text"
            # the body object is inside raw_payload (faithful upstream capture),
            # but no dedicated column ever surfaces body content
            assert "SECRET BODY CONTENT" not in snippet
            columns = [
                r[0]
                for r in cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='raw_gmail_messages'"
                ).fetchall()
            ]
            assert "body" not in columns


def test_gmail_credentials_missing(monkeypatch):
    """`pdw sync gmail` with no Google creds gives a clear error naming them."""
    import pdw.cli as cli

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: types.SimpleNamespace(
            google_client_id=None,
            google_client_secret=None,
            google_refresh_token=None,
        ),
    )
    result = CliRunner().invoke(cli.main, ["sync", "gmail"])
    assert result.exit_code != 0
    assert "GOOGLE_REFRESH_TOKEN" in result.output


# --- Spotify integration tests --------------------------------------------


def _spotify_play(track_id, played_at="2024-06-05T12:00:00.000Z"):
    return {
        "played_at": played_at,
        "track": {"id": track_id, "name": "Song", "artists": [{"name": "A"}]},
    }


def _spotify_fake(pages):
    fake = FakeHttpClient()
    for page in pages:
        fake.add("GET", "/me/player/recently-played", FakeResponse(json_data=page))
    return fake


def _spotify_connector(fake):
    return SpotifyConnector(SpotifyClient("access", http=HttpClient(fake)))


def test_spotify_loads_raw(clean_db: str):
    page = {
        "items": [
            _spotify_play("t1", "2024-06-05T12:00:00.000Z"),
            _spotify_play("t2", "2024-06-06T12:00:00.000Z"),
        ]
    }
    summary = run_spotify(_spotify_connector(_spotify_fake([page])), url=clean_db)

    assert summary.status == "success"
    assert _count(clean_db, "raw_spotify_plays", "WHERE source='spotify'") == 2
    assert (
        _count(clean_db, "pipeline_runs", "WHERE source='spotify' AND status='success'")
        == 1
    )
    # single 'primary' cursor under the spotify connector
    assert _count(clean_db, "sync_state", "WHERE connector='spotify'") == 1
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT track_id, artists FROM raw_spotify_plays "
                "WHERE source_id LIKE 't1:%'"
            )
            track_id, artists = cur.fetchone()
            assert track_id == "t1"
            assert artists == "A"


def test_spotify_idempotent(clean_db: str):
    page = {"items": [_spotify_play("t1", "2024-06-05T12:00:00.000Z")]}
    first = run_spotify(_spotify_connector(_spotify_fake([page])), url=clean_db)
    assert first.records_inserted == 1

    second = run_spotify(_spotify_connector(_spotify_fake([page])), url=clean_db)
    assert second.records_inserted == 0
    assert second.records_updated == 1
    assert _count(clean_db, "raw_spotify_plays") == 1  # no duplication


def test_spotify_incremental_ms_cursor(clean_db: str):
    """The cursor is played_at as epoch MILLISECONDS, forwarded as Spotify's
    `after` param on the next run."""
    page1 = {"items": [_spotify_play("t1", "2024-06-05T12:00:00.000Z")]}
    run_spotify(_spotify_connector(_spotify_fake([page1])), url=clean_db)

    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_cursor FROM sync_state "
                "WHERE connector='spotify' AND entity_key='primary'"
            )
            cursor = cur.fetchone()[0]
    # 2024-06-05T12:00:00Z == 1717588800000 ms
    assert cursor == "1717588800000"

    # Run 2: runner must request after=<cursor ms> and load the new play.
    page2 = {"items": [_spotify_play("t2", "2024-06-06T12:00:00.000Z")]}
    fake2 = _spotify_fake([page2])
    second = run_spotify(_spotify_connector(fake2), url=clean_db)

    assert second.records_inserted == 1
    params = fake2.params_for("/me/player/recently-played")[0]
    assert params["after"] == "1717588800000"
    assert _count(clean_db, "raw_spotify_plays") == 2


def test_spotify_credentials_missing(monkeypatch):
    """`pdw sync spotify` with no Spotify creds gives a clear error naming them."""
    import pdw.cli as cli

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: types.SimpleNamespace(
            spotify_client_id=None, spotify_refresh_token=None
        ),
    )
    result = CliRunner().invoke(cli.main, ["sync", "spotify"])
    assert result.exit_code != 0
    assert "SPOTIFY_CLIENT_ID" in result.output
