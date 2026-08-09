"""Integration tests for the synthetic load pipeline (spec §12, §13, §24, §26).

Covers: raw loading, idempotency (re-seed does not duplicate), pipeline-run
audit, and an optional end-to-end check that dbt analytics marts are populated
when the full pipeline has been run.
"""

import os

import psycopg
import pytest

from pdw.synthetic import generate, load

RAW_TABLES = [
    "raw_github_repositories",
    "raw_github_commits",
    "raw_github_pull_requests",
    "raw_github_issues",
    "raw_calendar_events",
    "raw_gmail_messages",
    "raw_spotify_plays",
]


def _counts(dsn: str) -> dict[str, int]:
    out: dict[str, int] = {}
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for t in RAW_TABLES:
                cur.execute(f"SELECT count(*) FROM {t}")
                out[t] = cur.fetchone()[0]
    return out


def test_seed_loads_raw(clean_db: str):
    ds = generate()
    summary = load(ds, clean_db)

    expected = len(ds.repos) + len(ds.commits) + len(ds.calendar_events)
    assert summary.records_fetched == expected
    assert summary.records_inserted == expected
    assert summary.records_updated == 0

    counts = _counts(clean_db)
    assert counts["raw_github_repositories"] == len(ds.repos)
    assert counts["raw_github_commits"] == len(ds.commits)
    assert counts["raw_calendar_events"] == len(ds.calendar_events)


def test_seed_is_idempotent(clean_db: str):
    """Re-running seed must not duplicate rows (spec §12, §13)."""
    ds = generate()
    first = load(ds, clean_db)
    assert first.records_inserted > 0

    before = _counts(clean_db)
    second = load(ds, clean_db)
    after = _counts(clean_db)

    assert before == after  # no new rows
    assert second.records_inserted == 0
    assert second.records_updated == first.records_inserted


def test_pipeline_run_recorded(clean_db: str):
    load(generate(), clean_db)
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, records_failed FROM pipeline_runs "
                "WHERE source = 'synthetic' ORDER BY started_at DESC LIMIT 1"
            )
            status, failed = cur.fetchone()
            assert status == "success"
            assert failed == 0


def test_sync_state_checkpointed(clean_db: str):
    load(generate(), clean_db)
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_successful_sync, last_cursor FROM sync_state "
                "WHERE connector = 'synthetic'"
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is not None
            assert row[1] is not None


def test_e2e_analytics_populated():
    """Optional E2E: if `make dbt` has run against the main db, marts are
    populated. Skipped when the analytics schema is absent (e.g. tests run
    before `make sync`)."""
    dsn = os.environ.get("DATABASE_URL", "postgresql://pdw:pdw@localhost:5432/pdw")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('analytics.mart_daily_activity')")
            if cur.fetchone()[0] is None:
                pytest.skip("analytics.mart_daily_activity not built — run `make dbt`")
            cur.execute("SELECT count(*) FROM analytics.mart_daily_activity")
            assert cur.fetchone()[0] > 0
            cur.execute("SELECT count(*) FROM analytics.mart_monthly_summary")
            assert cur.fetchone()[0] > 0
