# Personal Data Warehouse

A local-first personal data warehouse: ingest activity from external sources
(GitHub, Google Calendar), store raw data in PostgreSQL, transform it into
analytics-ready models with dbt, and expose metrics through a dashboard and a
natural-language AI interface.

This is a portfolio-quality data-engineering project demonstrating API
ingestion, ELT pipelines, PostgreSQL modeling, dbt transformations, incremental
+ idempotent loading, observability, and a layered architecture. See
[`spec.md`](./spec.md) for the full specification.

> **Status:** the foundation plus **real connectors** are in place —
> Dockerized PostgreSQL, raw schema + migrations, the full dbt transform path
> (staging → intermediate → marts + tests), and real **GitHub** + **Google
> Calendar** connectors with incremental + idempotent ingestion. The pipeline
> runs end-to-end on **synthetic data with no external credentials**
> (`make sync`), and on **real data** once credentials are added to `.env`
> (`make sync-real`). Dagster orchestration, the API, dashboard, and AI layer
> are deferred to later milestones.

## Architecture

The system is split into four strictly separated layers (spec §2):

```
External APIs → Ingestion (Python) → Raw PostgreSQL → dbt → Analytics → Presentation
```

- **Raw ingestion** — connectors load source data with minimal transformation,
  preserving original payloads as JSONB.
- **Transformation** — dbt builds staging → intermediate → marts.
- **Analytics** — star-schema facts/dimensions/marts.
- **Presentation / AI** — FastAPI, dashboard, LLM query layer (deferred).

See [`docs/architecture.md`](./docs/architecture.md) for diagrams and
[`docs/data-model.md`](./docs/data-model.md) for the analytical model.

## Tech stack

- Python 3.12 (uv), PostgreSQL 16, dbt-core + dbt-postgres
- psycopg, Pydantic v2, pytest, Ruff
- Docker / Docker Compose
- (Deferred) Dagster, FastAPI, Next.js, OpenAI-compatible LLM

## Local setup

Prerequisites: Docker (running), `uv`, `make`.

```bash
make setup        # enable docker compose, create .env, install deps, make test db
make up           # start PostgreSQL
make sync         # migrate -> seed synthetic data -> build dbt models + tests
make status       # show recent pipeline runs
```

To ingest **real** data instead of synthetic, add credentials to `.env` (see
below) then:

```bash
make reset         # clear raw + analytics so sources don't double-count
make sync-real     # sync GitHub + Google Calendar into raw tables
make dbt           # rebuild analytics marts from the real raw data
```

After `make sync`, inspect the analytics tables:

```bash
make psql
# => select count(*) from mart_daily_activity;
# => select * from mart_monthly_summary order by month desc limit 5;
```

## Make targets

| target        | description                                            |
| ------------- | ------------------------------------------------------ |
| `make setup`  | one-time bootstrap (compose plugin, .env, deps, test db) |
| `make up`     | start PostgreSQL                                       |
| `make down`   | stop the stack                                         |
| `make migrate`| apply SQL migrations (raw + ops tables)                |
| `make seed`   | generate + load synthetic data (idempotent)           |
| `make dbt`    | build dbt models + run tests (in container)            |
| `make sync`   | full synthetic pipeline: migrate → seed → dbt         |
| `make sync-github`   | sync real GitHub data (needs `GITHUB_TOKEN`)   |
| `make sync-calendar` | sync real Google Calendar data (needs `GOOGLE_*`) |
| `make sync-real`     | sync both real sources                          |
| `make reset`  | truncate raw + analytics, then rebuild dbt             |
| `make test`   | run pytest (unit + integration)                        |
| `make psql`   | open a psql session                                     |
| `make status` | show recent pipeline runs                              |

## Environment variables

Copy `.env.example` to `.env` (done by `make setup`). Only `DATABASE_URL`
(and the `POSTGRES_*` vars it derives from) are required for the synthetic
pipeline. Real connectors need:

- `GITHUB_TOKEN` — a GitHub personal access token (for `make sync-github`).
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`,
  `GOOGLE_CALENDAR_ID` (default `primary`) — for `make sync-calendar`. The
  refresh token is exchanged for a short-lived access token in memory per run
  and is **never stored in PostgreSQL** (spec §23).

**Never commit `.env`.** The app fails with a clear configuration error naming
the missing variable if a required one is absent (spec §7).

## How ingestion works

Each connector (`ingestion/src/pdw/connectors/`) wraps one HTTP API and
normalizes its responses into shared `pdw.models` records. The pipeline runner
(`ingestion/src/pdw/pipeline/`) fetches records, loads them into the raw tables
in a single idempotent transaction, advances per-entity cursors, and records a
`pipeline_runs` audit row (spec §9, §12, §24). Raw tables enforce natural keys
with unique constraints and loaders upsert via `ON CONFLICT`, so re-running a
sync never duplicates rows (spec §13).

- **GitHub** (`connectors/github.py`) — lists the authenticated user's repos and
  fetches commits per repo with a `since` cursor. Commit additions/deletions are
  stored as `NULL` because the list-commits endpoint does not return stats.
- **Google Calendar** (`connectors/calendar.py`) — refreshes an OAuth access
  token per run, then lists events. Incremental syncs use `updatedMin` (which
  returns modifications **and** cancellations); the initial backfill uses a
  `timeMin`/`timeMax` lookback window. All-day events use date-only values with
  an exclusive `end` (stored as `end.date + 1 day`).

Error handling (spec §25): auth failures and exhausted rate limits abort the
run with a clear message; per-repo failures (e.g. a 404) are counted and the run
completes as `partial`; malformed records are skipped + counted. Failed syncs
never corrupt existing data, and every run is safely re-runnable.

The **synthetic generator** (`ingestion/src/pdw/synthetic/`) stands in for the
connector layer when no credentials are set: it produces realistic repositories,
commits, and calendar events and loads them through the **same** shared loaders
as the real connectors, so the dbt models work identically against synthetic or
real data. Use `make reset` when switching between the two so sources don't
double-count in the marts.

## Data model

See [`docs/data-model.md`](./docs/data-model.md). In short: raw `raw_*` tables
feed dbt staging, which feeds intermediate models, which feed marts
(`dim_date`, `dim_repository`, `fct_commits`, `fct_calendar_events`,
`mart_daily_activity`, `mart_project_activity`, `mart_monthly_summary`).

## How to run tests

```bash
make test       # unit + integration (pytest, against a pdw_test database)
make dbt        # dbt tests run as part of `dbt build`
```

## How to add a connector

1. Create `ingestion/src/pdw/connectors/<source>.py` implementing the connector
   interface (`fetch` / `normalize` / `load`).
2. Add a `raw_<source>_<entity>` table + unique constraint in a new migration
   under `ingestion/src/pdw/migrations/sql/`.
3. Add dbt `stg_<source>_*` models and wire them into the relevant intermediate
   / mart models.
4. Add dbt tests (unique / not_null / relationships / accepted_values).
5. Add unit + integration tests for normalization, pagination, and idempotency.

The architecture is designed so this requires no changes to the pipeline
plumbing — only a new connector module, a raw table, and dbt models.