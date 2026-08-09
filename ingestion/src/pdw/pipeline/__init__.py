"""Pipeline orchestration: shared loaders, checkpoints, and runners.

The loaders here are source-agnostic — the same upserts serve the synthetic
stand-in and the real GitHub/Calendar connectors (spec §12, §13).
"""

from .checkpoints import get_cursor, set_cursor
from .loaders import (
    RunSummary,
    load_calendar,
    load_github,
    record_run,
    upsert_sync_state,
)
from .runner import run_calendar, run_github

__all__ = [
    "RunSummary",
    "get_cursor",
    "load_calendar",
    "load_github",
    "record_run",
    "run_calendar",
    "run_github",
    "set_cursor",
    "upsert_sync_state",
]