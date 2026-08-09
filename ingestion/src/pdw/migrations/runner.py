"""Idempotent SQL migration runner.

Migrations are plain ``.sql`` files in ``migrations/sql/``, applied in lexical
order. Applied versions are tracked in the ``schema_migrations`` table, so
running ``pdw migrate`` repeatedly is safe (spec §12 idempotency). This is
deliberately lightweight — Alembic is overkill for the small, stable raw
schema (spec §33).
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..db import connect

logger = logging.getLogger("pdw.migrations")

SQL_DIR = Path(__file__).parent / "sql"

CREATE_BOOKKEEPING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def _discover_migrations() -> list[tuple[str, Path]]:
    files = sorted(SQL_DIR.glob("*.sql"))
    return [(f.stem, f) for f in files]


def applied_versions(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row["version"] for row in cur.fetchall()}


def run_migrations(url: str | None = None) -> list[str]:
    """Apply all pending migrations. Returns the list of newly applied versions."""
    with connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_BOOKKEEPING)
        conn.commit()

        already = applied_versions(conn)
        pending = [(v, p) for v, p in _discover_migrations() if v not in already]

        applied: list[str] = []
        for version, path in pending:
            sql = path.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            conn.commit()
            applied.append(version)
            logger.info("applied migration %s", version)

        return applied
