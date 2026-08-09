"""Per-entity incremental cursors (spec §12).

Cursors are stored in ``sync_state`` keyed by ``(connector, entity_key)`` —
e.g. ``('github', 'gvleverett/personal-data-warehouse')`` for a single repo's
commit cursor, or ``('calendar', 'primary')`` for the calendar's
``updatedMin`` cursor. A cursor is the ISO-8601 timestamp of the newest
record seen; the next sync resumes from there.
"""

from __future__ import annotations

from .loaders import upsert_sync_state


def get_cursor(conn, connector: str, entity_key: str) -> str | None:
    """Return the stored cursor for an entity, or None if never synced."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_cursor FROM sync_state "
            "WHERE connector = %s AND entity_key = %s",
            (connector, entity_key),
        )
        row = cur.fetchone()
    return row["last_cursor"] if row else None


def set_cursor(conn, connector: str, entity_key: str, cursor: str) -> None:
    """Persist (advance) the cursor for an entity."""
    upsert_sync_state(conn, connector, entity_key, cursor)