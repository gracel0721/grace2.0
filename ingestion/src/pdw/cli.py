"""``pdw`` command-line interface (spec §18).

Subcommands:
    pdw migrate        — apply SQL migrations
    pdw seed           — generate + load synthetic data
    pdw status         — show recent pipeline runs (spec §24)
    pdw sync github    — sync real GitHub data (spec §6)
    pdw sync calendar  — sync real Google Calendar data (spec §6)
"""

from __future__ import annotations

import click

from .config import env_file, get_settings
from .db import connect
from .migrations import run_migrations
from .synthetic import generate, load


@click.group()
@click.version_option(package_name="pdw")
def main() -> None:
    """Personal Data Warehouse operator CLI."""


@main.command()
def migrate() -> None:
    """Apply pending SQL migrations to the raw + operational tables."""
    applied = run_migrations()
    if applied:
        click.echo(f"Applied migrations: {', '.join(applied)}")
    else:
        click.echo("No pending migrations; schema is up to date.")


@main.command()
def seed() -> None:
    """Generate and load synthetic data (idempotent)."""
    click.echo("Generating synthetic data...")
    dataset = generate()
    click.echo(
        f"  repos={len(dataset.repos)} commits={len(dataset.commits)} "
        f"events={len(dataset.calendar_events)}"
    )
    click.echo("Loading into raw tables...")
    summary = load(dataset)
    click.echo(
        f"  fetched={summary.records_fetched} "
        f"inserted={summary.records_inserted} updated={summary.records_updated} "
        f"failed={summary.records_failed}"
    )
    click.echo("Seed complete.")


@main.command()
def status() -> None:
    """Show recent pipeline runs (spec §24)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, status,
                       date_trunc('second', started_at) AS started_at,
                       records_fetched, records_inserted, records_updated,
                       records_failed
                FROM pipeline_runs
                ORDER BY started_at DESC
                LIMIT 10
                """
            )
            rows = cur.fetchall()

    if not rows:
        click.echo("No pipeline runs recorded yet. Run `pdw seed`.")
        return

    click.echo(
        f"{'source':<12} {'status':<10} {'started':<22} "
        f"{'fetched':>8} {'inserted':>9} {'updated':>8} {'failed':>7}"
    )
    click.echo("-" * 80)
    for r in rows:
        click.echo(
            f"{r['source']:<12} {r['status']:<10} "
            f"{str(r['started_at']):<22} "
            f"{r['records_fetched']:>8} {r['records_inserted']:>9} "
            f"{r['records_updated']:>8} {r['records_failed']:>7}"
        )


# ---------------------------------------------------------------------------
# Real connectors: `pdw sync github` / `pdw sync calendar` (spec §6, §25)
# ---------------------------------------------------------------------------
@main.group()
def sync() -> None:
    """Sync real external data (requires credentials in .env)."""


@sync.command()
@click.option("--full", is_flag=True, help="Backfill all history (ignore cursors).")
@click.option(
    "--since",
    type=int,
    default=90,
    show_default=True,
    help="Lookback window in days for the first/incremental sync.",
)
def github(full: bool, since: int) -> None:
    """Sync GitHub repositories + commits (spec §6)."""
    from .connectors.base import ConnectorError, HttpClient
    from .connectors.github import GitHubClient, GitHubConnector
    from .pipeline.runner import run_github

    settings = get_settings()
    if not settings.github_token:
        raise click.ClickException("GITHUB_TOKEN is not set. Add it to .env (spec §7).")

    import httpx

    client = HttpClient(
        httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
    )
    connector = GitHubConnector(GitHubClient(settings.github_token, client=client))
    click.echo("Syncing GitHub...")
    try:
        summary = run_github(connector, full=full, since_days=since)
    except ConnectorError as exc:
        raise click.ClickException(f"GitHub sync failed: {exc}") from exc
    click.echo(
        f"  fetched={summary.records_fetched} "
        f"inserted={summary.records_inserted} updated={summary.records_updated} "
        f"failed={summary.records_failed} status={summary.status}"
    )


@sync.command("github-issues")
@click.option("--full", is_flag=True, help="Backfill all history (ignore cursors).")
@click.option(
    "--since",
    type=int,
    default=90,
    show_default=True,
    help="Lookback window in days for the first/incremental sync.",
)
def github_issues(full: bool, since: int) -> None:
    """Sync GitHub pull requests + issues (spec §6)."""
    from .connectors.base import ConnectorError, HttpClient
    from .connectors.github import GitHubClient, GitHubIssuesConnector
    from .pipeline.runner import run_github_issues

    settings = get_settings()
    if not settings.github_token:
        raise click.ClickException("GITHUB_TOKEN is not set. Add it to .env (spec §7).")

    import httpx

    client = HttpClient(
        httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
    )
    connector = GitHubIssuesConnector(GitHubClient(settings.github_token, client=client))
    click.echo("Syncing GitHub PRs + Issues...")
    try:
        summary = run_github_issues(connector, full=full, since_days=since)
    except ConnectorError as exc:
        raise click.ClickException(f"GitHub sync failed: {exc}") from exc
    click.echo(
        f"  fetched={summary.records_fetched} "
        f"inserted={summary.records_inserted} updated={summary.records_updated} "
        f"failed={summary.records_failed} status={summary.status}"
    )


@sync.command()
@click.option(
    "--full", is_flag=True, help="Backfill the lookback window (ignore cursor)."
)
@click.option(
    "--since",
    type=int,
    default=90,
    show_default=True,
    help="Lookback window in days for the initial backfill.",
)
def calendar(full: bool, since: int) -> None:
    """Sync Google Calendar events (spec §6, §23)."""
    from .connectors.base import ConnectorError, HttpClient
    from .connectors.calendar import (
        CalendarClient,
        CalendarConnector,
        GoogleTokenRefresher,
    )
    from .pipeline.runner import run_calendar

    settings = get_settings()
    missing = [
        name
        for name, val in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
            ("GOOGLE_REFRESH_TOKEN", settings.google_refresh_token),
        )
        if not val
    ]
    if missing:
        raise click.ClickException(
            "Missing Google credentials: "
            + ", ".join(missing)
            + ". Add them to .env (spec §7, §23)."
        )

    import httpx

    http = HttpClient(httpx.Client(timeout=30.0))
    try:
        access_token = GoogleTokenRefresher(
            settings.google_client_id,
            settings.google_client_secret,
            http=http,
        ).refresh(settings.google_refresh_token)
    except ConnectorError as exc:
        raise click.ClickException(f"Google auth failed: {exc}") from exc

    cal_client = CalendarClient(access_token, http=http)
    connector = CalendarConnector(cal_client, calendar_id=settings.google_calendar_id)
    click.echo("Syncing Google Calendar...")
    try:
        summary = run_calendar(connector, full=full, since_days=since)
    except ConnectorError as exc:
        raise click.ClickException(f"Calendar sync failed: {exc}") from exc
    click.echo(
        f"  fetched={summary.records_fetched} "
        f"inserted={summary.records_inserted} updated={summary.records_updated} "
        f"failed={summary.records_failed} status={summary.status}"
    )


# ---------------------------------------------------------------------------
# One-time OAuth: `pdw auth google` (spec §23)
# ---------------------------------------------------------------------------
def _set_env_var(name: str, value: str) -> None:
    """Set or append a variable in the local .env (repo root)."""
    path = env_file()
    if not path.exists():
        path.write_text(f"{name}={value}\n")
        return
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    path.write_text("\n".join(lines) + "\n")


@main.group()
def auth() -> None:
    """One-time authorization flows for real connectors."""


@auth.command()
@click.option(
    "--port",
    type=int,
    default=8787,
    show_default=True,
    help="Loopback port for the OAuth redirect.",
)
def google(port: int) -> None:
    """Run the one-time Google OAuth flow and store the refresh token in .env."""
    from .connectors.auth import run_oauth_flow

    settings = get_settings()
    missing = [
        name
        for name, val in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
        )
        if not val
    ]
    if missing:
        raise click.ClickException(
            "Missing " + ", ".join(missing) + ". Add them to .env first (spec §7, §23)."
        )

    click.echo("Starting Google OAuth flow (calendar.readonly scope)...")
    try:
        refresh_token = run_oauth_flow(
            settings.google_client_id,
            settings.google_client_secret,
            port=port,
        )
    except Exception as exc:  # surface a clean message, not a traceback
        raise click.ClickException(f"OAuth flow failed: {exc}") from exc

    _set_env_var("GOOGLE_REFRESH_TOKEN", refresh_token)
    click.echo("Refresh token written to .env. You can now run: make sync-calendar")


if __name__ == "__main__":  # pragma: no cover
    main()
