"""PostgreSQL connection helpers (psycopg)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import get_settings


def get_dsn(url: str | None = None) -> str:
    """Return the connection string to use."""
    return url or get_settings().database_url


@contextmanager
def connect(url: str | None = None) -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection that commits on success, closes always."""
    conn = psycopg.connect(get_dsn(url), row_factory=dict_row, autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
