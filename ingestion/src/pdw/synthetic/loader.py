"""Synthetic data loader (spec §12, §13, §24).

Thin wrapper over the shared ``pipeline.loaders`` upserts. The synthetic
dataset is loaded as ``source='synthetic'`` into the same raw tables the real
connectors use, with a single synthetic ``pipeline_runs`` audit row and a
``sync_state`` checkpoint so ``pdw status`` reflects the run.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..db import connect
from ..pipeline.loaders import (
    CALENDAR,
    GITHUB,
    RunSummary,
    _load_calendar,
    _load_commits,
    _load_repos,
    record_run,
    upsert_sync_state,
)
from .generator import SyntheticDataset

SOURCE = "synthetic"

__all__ = ["RunSummary", "load"]


def load(dataset: SyntheticDataset, url: str | None = None) -> RunSummary:
    """Load a synthetic dataset into raw tables and record the run."""
    started = datetime.now(UTC)
    with connect(url) as conn:
        with conn.cursor() as cur:
            ri, ru = _load_repos(cur, dataset.repos, GITHUB)
            ci, cu = _load_commits(cur, dataset.commits, GITHUB)
            ei, eu = _load_calendar(cur, dataset.calendar_events, CALENDAR)

        inserted = ri + ci + ei
        updated = ru + cu + eu
        fetched = len(dataset.repos) + len(dataset.commits) + len(
            dataset.calendar_events
        )
        summary = RunSummary(
            records_fetched=fetched,
            records_inserted=inserted,
            records_updated=updated,
            records_failed=0,
        )

        record_run(conn, SOURCE, started, summary)
        upsert_sync_state(conn, SOURCE, "all", started.isoformat())
    return summary