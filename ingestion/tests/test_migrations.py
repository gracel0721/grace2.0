"""Integration tests for the migration runner (spec §26)."""

import psycopg

from pdw.migrations import run_migrations

EXPECTED_TABLES = [
    "raw_github_repositories",
    "raw_github_commits",
    "raw_calendar_events",
    "pipeline_runs",
    "sync_state",
    "schema_migrations",
]


def test_migrations_create_tables(clean_db: str):
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass(%s)", (f"public.{EXPECTED_TABLES[0]}",)
            )
            # check each table exists
            for t in EXPECTED_TABLES:
                cur.execute("SELECT to_regclass(%s)", (f"public.{t}",))
                assert cur.fetchone()[0] is not None, f"missing table {t}"


def test_migrations_idempotent(clean_db: str):
    # Migrations were applied by the session fixture; re-running applies nothing.
    applied = run_migrations(clean_db)
    assert applied == []

    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            assert cur.fetchone()[0] == 1  # only 0001_init