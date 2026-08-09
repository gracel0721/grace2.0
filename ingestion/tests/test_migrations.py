"""Integration tests for the migration runner (spec §26)."""

import psycopg

from pdw.migrations import run_migrations

EXPECTED_TABLES = [
    "raw_github_repositories",
    "raw_github_commits",
    "raw_github_pull_requests",
    "raw_github_issues",
    "raw_calendar_events",
    "raw_gmail_messages",
    "raw_spotify_plays",
    "pipeline_runs",
    "sync_state",
    "schema_migrations",
]


def test_migrations_create_tables(clean_db: str):
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (f"public.{EXPECTED_TABLES[0]}",))
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
            # 0001..0005 (init, sync_state_entity, github_prs_issues, gmail, spotify)
            assert cur.fetchone()[0] == 5


def test_sync_state_has_entity_key(clean_db: str):
    """Migration 0002 adds entity_key + a composite primary key (spec §12)."""
    with psycopg.connect(clean_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a
                  ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = 'sync_state'::regclass AND i.indisprimary
                ORDER BY array_position(i.indkey, a.attnum)
                """
            )
            pk_cols = [r[0] for r in cur.fetchall()]
            assert pk_cols == ["connector", "entity_key"]

            cur.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'sync_state' AND column_name = 'entity_key'"
            )
            assert cur.fetchone()[0] == "NO"
