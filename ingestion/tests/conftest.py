"""Pytest fixtures.

Unit tests (categorize, generator) need no database. Integration tests use a
separate ``pdw_test`` database (created on demand) so they never touch real
data. The ``pdw_test`` DSN is derived from ``DATABASE_URL`` by swapping the
database name.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

from pdw.migrations import run_migrations

RAW_TABLES = [
    "raw_github_repositories",
    "raw_github_commits",
    "raw_github_pull_requests",
    "raw_github_issues",
    "raw_calendar_events",
    "pipeline_runs",
    "sync_state",
]


def _to_test_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path="/pdw_test"))


@pytest.fixture(scope="session")
def test_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL", "postgresql://pdw:pdw@localhost:5432/pdw")
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = 'pdw_test'")
                if not cur.fetchone():
                    cur.execute("CREATE DATABASE pdw_test")
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    test = _to_test_dsn(dsn)
    run_migrations(test)  # ensure schema exists for the session
    return test


@pytest.fixture()
def clean_db(test_dsn: str) -> str:
    """Truncate raw/ops tables before each test for isolation."""
    with psycopg.connect(test_dsn) as conn:
        with conn.cursor() as cur:
            for table in RAW_TABLES:
                cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
        conn.commit()
    return test_dsn


def row_counts(dsn: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for table in RAW_TABLES:
                cur.execute(f"SELECT count(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
    return counts
