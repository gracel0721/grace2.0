"""Idempotent loader for synthetic data (spec §12, §13).

Upserts each record into the matching raw table on its natural key using
``ON CONFLICT … DO UPDATE``, so re-running ``make seed`` never duplicates rows.
Insert vs. update is detected via the Postgres ``xmax = 0`` trick on RETURNING.
A ``pipeline_runs`` audit row and a ``sync_state`` checkpoint are written so
``pdw status`` reflects the run (spec §24).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from psycopg.types.json import Jsonb

from ..db import connect
from .generator import CalendarEvent, Commit, Repo, SyntheticDataset

SOURCE = "synthetic"
GITHUB = "github"
CALENDAR = "calendar"


@dataclass
class RunSummary:
    records_fetched: int
    records_inserted: int
    records_updated: int
    records_failed: int


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


def _load_repos(cur, repos: list[Repo]) -> tuple[int, int]:
    inserted = updated = 0
    for r in repos:
        payload = {
            "id": r.github_repository_id,
            "name": r.name,
            "owner": r.owner,
            "full_name": r.full_name,
            "language": r.language,
            "created_at": r.created_at.isoformat(),
            "archived": r.archived,
        }
        if _upsert(
            cur,
            _REPO_SQL,
            (
                GITHUB,
                r.source_id,
                r.github_repository_id,
                r.name,
                r.owner,
                r.full_name,
                r.language,
                r.created_at,
                r.archived,
                Jsonb(payload),
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


def _load_commits(cur, commits: list[Commit]) -> tuple[int, int]:
    inserted = updated = 0
    for c in commits:
        payload = {
            "sha": c.commit_sha,
            "author": {"name": c.author_name, "email": c.author_email},
            "committed_at": c.committed_at.isoformat(),
            "additions": c.additions,
            "deletions": c.deletions,
            "message": c.message,
            "repository": c.repository_source_id,
        }
        if _upsert(
            cur,
            _COMMIT_SQL,
            (
                GITHUB,
                c.source_id,
                c.repository_source_id,
                c.commit_sha,
                c.author_name,
                c.author_email,
                c.committed_at,
                c.additions,
                c.deletions,
                c.message,
                Jsonb(payload),
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


def _load_calendar(cur, events: list[CalendarEvent]) -> tuple[int, int]:
    inserted = updated = 0
    for e in events:
        payload = {
            "id": e.source_id,
            "title": e.title,
            "start": e.start_at.isoformat(),
            "end": e.end_at.isoformat(),
            "timezone": e.timezone,
            "attendees_count": e.attendees_count,
            "status": e.status,
            "category": e.category,
        }
        if _upsert(
            cur,
            _CAL_SQL,
            (
                CALENDAR,
                e.calendar_id,
                e.source_id,
                e.title,
                e.start_at,
                e.end_at,
                e.timezone,
                e.attendees_count,
                e.status,
                e.category,
                Jsonb(payload),
            ),
        ):
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def load(dataset: SyntheticDataset, url: str | None = None) -> RunSummary:
    """Load a synthetic dataset into raw tables and record the run."""
    from datetime import datetime

    started = datetime.now(UTC)
    with connect(url) as conn:
        with conn.cursor() as cur:
            ri, ru = _load_repos(cur, dataset.repos)
            ci, cu = _load_commits(cur, dataset.commits)
            ei, eu = _load_calendar(cur, dataset.calendar_events)

        inserted = ri + ci + ei
        updated = ru + cu + eu
        fetched = len(dataset.repos) + len(dataset.commits) + len(
            dataset.calendar_events
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs
                    (source, started_at, finished_at, status,
                     records_fetched, records_inserted,
                     records_updated, records_failed)
                VALUES (%s, %s, now(), 'success', %s, %s, %s, 0)
                """,
                (SOURCE, started, fetched, inserted, updated),
            )
            cur.execute(
                """
                INSERT INTO sync_state
                    (connector, last_successful_sync, last_cursor,
                     source_updated_at, updated_at)
                VALUES (%s, now(), %s, now(), now())
                ON CONFLICT (connector) DO UPDATE SET
                    last_successful_sync = now(),
                    last_cursor = EXCLUDED.last_cursor,
                    source_updated_at = now(),
                    updated_at = now()
                """,
                (SOURCE, started.isoformat()),
            )
    return RunSummary(
        records_fetched=fetched,
        records_inserted=inserted,
        records_updated=updated,
        records_failed=0,
    )