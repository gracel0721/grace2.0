"""Pipeline runners: orchestrate fetch -> load -> checkpoint (spec §12, §25).

Each runner drives one connector through a full or incremental sync:

  1. Fetch records over the network (outside any DB transaction, so an
     abort-level error during fetch leaves the database untouched).
  2. Load them into the raw tables in a single transaction (idempotent upserts,
     spec §13) and advance per-entity cursors.
  3. Record one ``pipeline_runs`` audit row (spec §24).

Abort-level errors (AuthError, RateLimitError, NetworkError) are recorded as a
``failed`` run in a separate transaction and re-raised so the CLI can surface a
clear message. Per-entity failures (one repo 404s, a malformed record) are
counted and the run completes with ``status='partial'``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..connectors.base import (
    ApiError,
    AuthError,
    MalformedRecordError,
    NetworkError,
    RateLimitError,
)
from ..db import connect
from .checkpoints import get_cursor, set_cursor
from .loaders import (
    CALENDAR,
    GITHUB,
    GMAIL,
    RunSummary,
    _load_calendar,
    _load_commits,
    _load_emails,
    _load_issues,
    _load_prs,
    _load_repos,
    record_run,
)

GITHUB_CONNECTOR = "github"
GITHUB_ISSUES_CONNECTOR = "github_issues"
CALENDAR_CONNECTOR = "calendar"
GMAIL_CONNECTOR = "gmail"


def _all_cursors(conn, connector: str) -> dict[str, str]:
    """Return {entity_key: last_cursor} for every entity of a connector."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT entity_key, last_cursor FROM sync_state WHERE connector = %s",
            (connector,),
        )
        return {row["entity_key"]: row["last_cursor"] for row in cur.fetchall()}


def _record_failure(
    url: str | None, source: str, started: datetime, exc: Exception
) -> None:
    """Best-effort: write a ``failed`` audit row after an abort-level error."""
    summary = RunSummary(0, 0, 0, 0, status="failed", error_message=str(exc))
    try:
        with connect(url) as conn:
            record_run(conn, source, started, summary)
    except Exception:  # pragma: no cover - never mask the original error
        pass


def run_github(
    connector,
    *,
    url: str | None = None,
    full: bool = False,
    since_days: int = 90,
) -> RunSummary:
    """Sync GitHub repositories + commits incrementally (spec §12)."""
    started = datetime.now(UTC)
    try:
        repos = connector.fetch_repos()  # network; may raise Auth/RateLimit/Net

        # Read existing per-repo cursors in a short-lived transaction.
        with connect(url) as conn:
            cursors = {} if full else _all_cursors(conn, GITHUB_CONNECTOR)

        default_since = started - timedelta(days=since_days)
        commits_by_repo: dict[str, list] = {}
        failures = 0
        partial = False

        for repo in repos:
            since = (
                None
                if full
                else (_parse_cursor(cursors.get(repo.source_id)) or default_since)
            )
            try:
                commits_by_repo[repo.source_id] = connector.fetch_commits(
                    repo, since=since
                )
            except (ApiError, MalformedRecordError):  # per-repo -> skip, continue
                failures += 1
                partial = True

        # Single write transaction: load repos + commits, advance cursors.
        total_commits = 0
        with connect(url) as conn:
            with conn.cursor() as cur:
                ri, ru = _load_repos(cur, repos, GITHUB)
                ci = cu = 0
                for repo in repos:
                    commits = commits_by_repo.get(repo.source_id)
                    if commits is None:
                        continue
                    i, u = _load_commits(cur, commits, GITHUB)
                    ci += i
                    cu += u
                    total_commits += len(commits)
                    # Advance the cursor to the newest commit seen for this
                    # repo; if no new commits, leave the cursor so the next run
                    # re-checks (idempotent, catches late-pushed commits).
                    if commits:
                        latest = max(c.committed_at for c in commits)
                        set_cursor(
                            conn,
                            GITHUB_CONNECTOR,
                            repo.source_id,
                            latest.isoformat(),
                        )

            fetched = len(repos) + total_commits
            summary = RunSummary(
                records_fetched=fetched,
                records_inserted=ri + ci,
                records_updated=ru + cu,
                records_failed=failures,
                status="partial" if partial else "success",
            )
            record_run(conn, GITHUB, started, summary)
        return summary
    except (AuthError, RateLimitError, NetworkError) as exc:
        _record_failure(url, GITHUB, started, exc)
        raise


def run_github_issues(
    connector,
    *,
    url: str | None = None,
    full: bool = False,
    since_days: int = 90,
) -> RunSummary:
    """Sync GitHub pull requests + issues incrementally (spec §12).

    Mirrors ``run_github``: fetch repos, then per repo fetch issues+PRs with a
    ``since`` cursor (the max ``updated_at`` already seen), and load everything
    in one transaction. Repos are loaded too so the dbt ``repository_key``
    relationship resolves even when commits haven't been synced. Per-repo
    failures (one repo 404s) are counted as ``partial``; abort-level errors
    (auth/rate-limit/network) record a ``failed`` run and re-raise.
    """
    started = datetime.now(UTC)
    try:
        repos = connector.fetch_repos()  # network; may raise Auth/RateLimit/Net

        with connect(url) as conn:
            cursors = {} if full else _all_cursors(conn, GITHUB_ISSUES_CONNECTOR)

        default_since = started - timedelta(days=since_days)
        results: dict[str, tuple[list, list]] = {}
        failures = 0
        partial = False

        for repo in repos:
            since = (
                None
                if full
                else (_parse_cursor(cursors.get(repo.source_id)) or default_since)
            )
            try:
                results[repo.source_id] = connector.fetch_issues_prs(repo, since=since)
            except (ApiError, MalformedRecordError):  # per-repo -> skip, continue
                failures += 1
                partial = True

        # Single write transaction: load repos + issues + PRs, advance cursors.
        total_items = 0
        with connect(url) as conn:
            with conn.cursor() as cur:
                ri, ru = _load_repos(cur, repos, GITHUB)
                pi = pu = ii = iu = 0
                for repo in repos:
                    res = results.get(repo.source_id)
                    if res is None:
                        continue
                    issues, prs = res
                    a, b = _load_issues(cur, issues, GITHUB)
                    ii += a
                    iu += b
                    c, d = _load_prs(cur, prs, GITHUB)
                    pi += c
                    pu += d
                    total_items += len(issues) + len(prs)
                    items = issues + prs
                    if items:
                        latest = max(x.updated_at for x in items)
                        set_cursor(
                            conn,
                            GITHUB_ISSUES_CONNECTOR,
                            repo.source_id,
                            latest.isoformat(),
                        )

            fetched = len(repos) + total_items
            summary = RunSummary(
                records_fetched=fetched,
                records_inserted=ri + pi + ii,
                records_updated=ru + pu + iu,
                records_failed=failures,
                status="partial" if partial else "success",
            )
            record_run(conn, GITHUB, started, summary)
        return summary
    except (AuthError, RateLimitError, NetworkError) as exc:
        _record_failure(url, GITHUB, started, exc)
        raise


def run_calendar(
    connector,
    *,
    url: str | None = None,
    full: bool = False,
    since_days: int = 90,
) -> RunSummary:
    """Sync Google Calendar events incrementally (spec §12, §23)."""
    started = datetime.now(UTC)
    try:
        cursor = None
        if not full:
            with connect(url) as conn:
                cursor = get_cursor(conn, CALENDAR_CONNECTOR, "primary")

        if cursor and not full:
            events = connector.fetch_events(updated_min=_parse_cursor(cursor))
        else:
            time_min = started - timedelta(days=since_days)
            events = connector.fetch_events(time_min=time_min, time_max=started)

        with connect(url) as conn:
            with conn.cursor() as cur:
                ei, eu = _load_calendar(cur, events, CALENDAR)
            # Calendar cursor = now; updatedMin catches future updates + deletes.
            set_cursor(conn, CALENDAR_CONNECTOR, "primary", started.isoformat())

            summary = RunSummary(
                records_fetched=len(events),
                records_inserted=ei,
                records_updated=eu,
                records_failed=0,
                status="success",
            )
            record_run(conn, CALENDAR, started, summary)
        return summary
    except (AuthError, RateLimitError, NetworkError) as exc:
        _record_failure(url, CALENDAR, started, exc)
        raise


def run_gmail(
    connector,
    *,
    url: str | None = None,
    full: bool = False,
    since_days: int = 90,
) -> RunSummary:
    """Sync Gmail messages incrementally, metadata only (spec §3, §12, §23).

    Mirrors ``run_calendar``'s single-entity ``"primary"`` cursor. Gmail search
    is date-granular (``q=after:YYYY/MM/DD``), so the cursor (the newest message
    ``date`` seen) is converted to a day boundary; the overlap on the cursor day
    is harmless because raw upserts are idempotent (spec §13). With no cursor
    the first sync backfills ``since_days`` of history.
    """
    started = datetime.now(UTC)
    try:
        cursor = None
        if not full:
            with connect(url) as conn:
                cursor = get_cursor(conn, GMAIL_CONNECTOR, "primary")

        if cursor and not full:
            after_date = _parse_cursor(cursor).strftime("%Y/%m/%d")
        else:
            after_date = (started - timedelta(days=since_days)).strftime("%Y/%m/%d")

        emails = connector.fetch_messages(after=after_date)

        with connect(url) as conn:
            with conn.cursor() as cur:
                ei, eu = _load_emails(cur, emails, GMAIL)
            # Advance the cursor to the newest message date seen, or now() if the
            # mailbox returned nothing new (so the next run resumes from today).
            latest = max((e.date for e in emails), default=started)
            set_cursor(conn, GMAIL_CONNECTOR, "primary", latest.isoformat())

            summary = RunSummary(
                records_fetched=len(emails),
                records_inserted=ei,
                records_updated=eu,
                records_failed=0,
                status="success",
            )
            record_run(conn, GMAIL, started, summary)
        return summary
    except (AuthError, RateLimitError, NetworkError) as exc:
        _record_failure(url, GMAIL, started, exc)
        raise


def _parse_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    return datetime.fromisoformat(cursor)
