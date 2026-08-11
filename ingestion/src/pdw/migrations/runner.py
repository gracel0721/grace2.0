"""Idempotent SQL migration runner.

Migrations are plain ``.sql`` files in ``migrations/sql/``, applied in lexical
order. Applied versions are tracked in the ``schema_migrations`` table, so
running ``pdw migrate`` repeatedly is safe (spec §12 idempotency). This is
deliberately lightweight — Alembic is overkill for the small, stable raw
schema (spec §33).

Phase 1 of the Personal Developer OS adds an additive extension: an
``PDW_EXTRA_MIGRATIONS_DIR`` env var, if set to a directory containing
``*.sql`` files, is also scanned and merged with the built-in discovery.
Dedup is by stem (filename without ``.sql``); on conflict, the OS-side
file (lexically later) wins.
"""

from __future__ import annotations

import logging
import os
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
    extra = os.environ.get("PDW_EXTRA_MIGRATIONS_DIR", "").strip()
    if extra:
        extra_dir = Path(extra).resolve()
        if extra_dir.is_dir():
            files += sorted(extra_dir.glob("*.sql"))
    # Dedup by stem; later lexical wins (so OS files override grace2.0
    # if the user places a same-named file there).
    by_stem: dict[str, Path] = {}
    for f in files:
        by_stem[f.stem] = f
    return sorted(by_stem.items())


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
