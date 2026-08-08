"""``pdw`` command-line interface (spec §18).

Subcommands:
    pdw migrate   — apply SQL migrations
    pdw seed      — generate + load synthetic data
    pdw status    — show recent pipeline runs (spec §24)
"""

from __future__ import annotations

import click

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


if __name__ == "__main__":  # pragma: no cover
    main()