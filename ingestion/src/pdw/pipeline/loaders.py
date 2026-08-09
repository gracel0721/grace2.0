"""Source-agnostic idempotent loaders for the raw tables (spec §12, §13).

Upserts each record into its raw table on the natural key using
``ON CONFLICT … DO UPDATE``, so re-running a sync never duplicates rows.
Insert vs. update is detected via the Postgres ``xmax = 0`` trick on RETURNING.
The ``raw_payload`` stored is the record's own ``raw_payload`` (the original
source JSON for real connectors, a constructed stand-in for synthetic data).

Both the synthetic loader and the real connectors call ``load_github`` /
``load_calendar`` so they share one code path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from psycopg.types.json import Jsonb

from ..db import connect
from ..models import CalendarEvent, Commit, Email, Issue, PullRequest, Repo

GITHUB = "github"
CALENDAR = "calendar"
GMAIL = "gmail"


@dataclass
class RunSummary:
    records_fetched: int
    records_inserted: int
    records_updated: int
    records_failed: int
    status: str = "success"
    error_message: str | None = None


def _upsert(cur, query: str, params: tuple) -> bool:
    """Execute an upsert; return True if the row was newly inserted."""
    cur.execute(query + " RETURNING (xmax = 0) AS inserted", params)
    row = cur.fetchone()
    return bool(row["inserted"])


_REPO_SQL = """
INSERT INTO raw_github_repositories
    (source, source_id, github_repository_id, name, owner, full_name,
     language, created_at, archived, raw_payload)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source, source_id) DO UPDATE SET
    github_repository_id = EXCLUDED.github_repository_id,
    name = EXCLUDED.name,
    owner = EXCLUDED.owner,
    full_name = EXCLUDED.full_name,
    language = EXCLUDED.language,
    created_at = EXCLUDED.created_at,
    archived = EXCLUDED.archived,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = now()
"""


def _load_repos(cur, repos: Iterable[Repo], source: str) -> tuple[int, int]:
    inserted = updated = 0
    for r in repos:
        if _upsert(
            cur,
            _REPO_SQL,
            (
                source,
                r.source_id,
                r.github_repository_id,
                r.name,
                r.owner,
                r.full_name,
                r.language,
                r.created_at,
                r.archived,
                Jsonb(r.raw_payload or {}),
            ),
        ):
            inserted += 1
        else:
            updated += 1
    return inserted, updated


_COMMIT_SQL = """
INSERT INTO raw_github_commits
    (source, source_id, repository_source_id, commit_sha, author_name,
     author_email, committed_at, additions, deletions, message, raw_payload)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source, source_id) DO UPDATE SET
    repository_source_id = EXCLUDED.repository_source_id,
    commit_sha = EXCLUDED.commit_sha,
    author_name = EXCLUDED.author_name,
    author_email = EXCLUDED.author_email,
    committed_at = EXCLUDED.committed_at,
    additions = EXCLUDED.additions,
    deletions = EXCLUDED.deletions,
    message = EXCLUDED.message,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = now()
"""


def _load_commits(cur, commits: Iterable[Commit], source: str) -> tuple[int, int]:
    inserted = updated = 0
    for c in commits:
        if _upsert(
            cur,
            _COMMIT_SQL,
            (
                source,
                c.source_id,
                c.repository_source_id,
                c.commit_sha,
                c.author_name,
                c.author_email,
                c.committed_at,
                c.additions,
                c.deletions,
                c.message,
                Jsonb(c.raw_payload or {}),
            ),
        ):
            inserted += 1
        else:
            updated += 1
    return inserted, updated


_CAL_SQL = """
INSERT INTO raw_calendar_events
    (source, calendar_id, source_id, title, start_at, end_at, timezone,
     attendees_count, status, category, raw_payload)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source, calendar_id, source_id) DO UPDATE SET
    title = EXCLUDED.title,
    start_at = EXCLUDED.start_at,
    end_at = EXCLUDED.end_at,
    timezone = EXCLUDED.timezone,
    attendees_count = EXCLUDED.attendees_count,
    status = EXCLUDED.status,
    category = EXCLUDED.category,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = now()
"""


def _load_calendar(cur, events: Iterable[CalendarEvent], source: str) -> tuple[int, int]:
    inserted = updated = 0
    for e in events:
        if _upsert(
            cur,
            _CAL_SQL,
            (
                source,
                e.calendar_id,
                e.source_id,
                e.title,
                e.start_at,
                e.end_at,
                e.timezone,
                e.attendees_count,
                e.status,
                e.category,
                Jsonb(e.raw_payload or {}),
            ),
        ):
            inserted += 1
        else:
            updated += 1
    return inserted, updated


_PR_SQL = """
INSERT INTO raw_github_pull_requests
    (source, source_id, repository_source_id, number, title, state, author,
     created_at, updated_at, closed_at, merged_at, is_draft, comments_count,
     raw_payload)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source, source_id) DO UPDATE SET
    repository_source_id = EXCLUDED.repository_source_id,
    number = EXCLUDED.number,
    title = EXCLUDED.title,
    state = EXCLUDED.state,
    author = EXCLUDED.author,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at,
    closed_at = EXCLUDED.closed_at,
    merged_at = EXCLUDED.merged_at,
    is_draft = EXCLUDED.is_draft,
    comments_count = EXCLUDED.comments_count,
    raw_payload = EXCLUDED.raw_payload
"""


def _load_prs(cur, prs: Iterable[PullRequest], source: str) -> tuple[int, int]:
    inserted = updated = 0
    for p in prs:
        if _upsert(
            cur,
            _PR_SQL,
            (
                source,
                p.source_id,
                p.repository_source_id,
                p.number,
                p.title,
                p.state,
                p.author,
                p.created_at,
                p.updated_at,
                p.closed_at,
                p.merged_at,
                p.is_draft,
                p.comments_count,
                Jsonb(p.raw_payload or {}),
            ),
        ):
            inserted += 1
        else:
            updated += 1
    return inserted, updated


_ISSUE_SQL = """
INSERT INTO raw_github_issues
    (source, source_id, repository_source_id, number, title, state,
     state_reason, author, created_at, updated_at, closed_at, comments_count,
     raw_payload)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source, source_id) DO UPDATE SET
    repository_source_id = EXCLUDED.repository_source_id,
    number = EXCLUDED.number,
    title = EXCLUDED.title,
    state = EXCLUDED.state,
    state_reason = EXCLUDED.state_reason,
    author = EXCLUDED.author,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at,
    closed_at = EXCLUDED.closed_at,
    comments_count = EXCLUDED.comments_count,
    raw_payload = EXCLUDED.raw_payload
"""


def _load_issues(cur, issues: Iterable[Issue], source: str) -> tuple[int, int]:
    inserted = updated = 0
    for i in issues:
        if _upsert(
            cur,
            _ISSUE_SQL,
            (
                source,
                i.source_id,
                i.repository_source_id,
                i.number,
                i.title,
                i.state,
                i.state_reason,
                i.author,
                i.created_at,
                i.updated_at,
                i.closed_at,
                i.comments_count,
                Jsonb(i.raw_payload or {}),
            ),
        ):
            inserted += 1
        else:
            updated += 1
    return inserted, updated


_EMAIL_SQL = """
INSERT INTO raw_gmail_messages
    (source, source_id, thread_id, sender, recipients, subject, date, snippet,
     raw_payload)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source, source_id) DO UPDATE SET
    thread_id = EXCLUDED.thread_id,
    sender = EXCLUDED.sender,
    recipients = EXCLUDED.recipients,
    subject = EXCLUDED.subject,
    date = EXCLUDED.date,
    snippet = EXCLUDED.snippet,
    raw_payload = EXCLUDED.raw_payload,
    updated_at = now()
"""


def _load_emails(cur, emails: Iterable[Email], source: str) -> tuple[int, int]:
    inserted = updated = 0
    for e in emails:
        if _upsert(
            cur,
            _EMAIL_SQL,
            (
                source,
                e.source_id,
                e.thread_id,
                e.sender,
                e.recipients,
                e.subject,
                e.date,
                e.snippet,
                Jsonb(e.raw_payload or {}),
            ),
        ):
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def record_run(conn, source: str, started: datetime, summary: RunSummary) -> None:
    """Write one ``pipeline_runs`` audit row from a RunSummary (spec §24)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_runs
                (source, started_at, finished_at, status,
                 records_fetched, records_inserted,
                 records_updated, records_failed, error_message)
            VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s)
            """,
            (
                source,
                started,
                summary.status,
                summary.records_fetched,
                summary.records_inserted,
                summary.records_updated,
                summary.records_failed,
                summary.error_message,
            ),
        )


def upsert_sync_state(conn, connector: str, entity_key: str, last_cursor: str) -> None:
    """Upsert a per-entity incremental checkpoint (spec §12)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_state
                (connector, entity_key, last_successful_sync, last_cursor,
                 source_updated_at, updated_at)
            VALUES (%s, %s, now(), %s, now(), now())
            ON CONFLICT (connector, entity_key) DO UPDATE SET
                last_successful_sync = now(),
                last_cursor = EXCLUDED.last_cursor,
                source_updated_at = now(),
                updated_at = now()
            """,
            (connector, entity_key, last_cursor),
        )


def load_github(
    repos: Iterable[Repo],
    commits: Iterable[Commit],
    *,
    url: str | None = None,
    source: str = GITHUB,
    record_run: bool = True,
) -> RunSummary:
    """Load repos + commits into the raw GitHub tables.

    When ``record_run`` is True (real connectors) a ``pipeline_runs`` audit row
    is written. The synthetic loader passes ``record_run=False`` and writes its
    own single synthetic audit row.
    """
    from datetime import UTC

    repos = list(repos)
    commits = list(commits)
    started = datetime.now(UTC)
    with connect(url) as conn:
        with conn.cursor() as cur:
            ri, ru = _load_repos(cur, repos, source)
            ci, cu = _load_commits(cur, commits, source)

        summary = RunSummary(
            records_fetched=len(repos) + len(commits),
            records_inserted=ri + ci,
            records_updated=ru + cu,
            records_failed=0,
        )
        if record_run:
            record_run(conn, source, started, summary)
    return summary


def load_calendar(
    events: Iterable[CalendarEvent],
    *,
    url: str | None = None,
    source: str = CALENDAR,
    record_run: bool = True,
) -> RunSummary:
    """Load calendar events into the raw calendar table."""
    from datetime import UTC

    events = list(events)
    started = datetime.now(UTC)
    with connect(url) as conn:
        with conn.cursor() as cur:
            ei, eu = _load_calendar(cur, events, source)

        summary = RunSummary(
            records_fetched=len(events),
            records_inserted=ei,
            records_updated=eu,
            records_failed=0,
        )
        if record_run:
            record_run(conn, source, started, summary)
    return summary


def load_gmail(
    emails: Iterable[Email],
    *,
    url: str | None = None,
    source: str = GMAIL,
    record_run: bool = True,
) -> RunSummary:
    """Load Gmail messages (metadata only) into the raw gmail table."""
    from datetime import UTC

    emails = list(emails)
    started = datetime.now(UTC)
    with connect(url) as conn:
        with conn.cursor() as cur:
            ei, eu = _load_emails(cur, emails, source)

        summary = RunSummary(
            records_fetched=len(emails),
            records_inserted=ei,
            records_updated=eu,
            records_failed=0,
        )
        if record_run:
            record_run(conn, source, started, summary)
    return summary


def load_github_issues(
    prs: Iterable[PullRequest],
    issues: Iterable[Issue],
    *,
    url: str | None = None,
    source: str = GITHUB,
    record_run: bool = True,
) -> RunSummary:
    """Load GitHub PRs + issues into their raw tables (spec §13 idempotent)."""
    from datetime import UTC

    prs = list(prs)
    issues = list(issues)
    started = datetime.now(UTC)
    with connect(url) as conn:
        with conn.cursor() as cur:
            pi, pu = _load_prs(cur, prs, source)
            ii, iu = _load_issues(cur, issues, source)

        summary = RunSummary(
            records_fetched=len(prs) + len(issues),
            records_inserted=pi + ii,
            records_updated=pu + iu,
            records_failed=0,
        )
        if record_run:
            record_run(conn, source, started, summary)
    return summary
