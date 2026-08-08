# Personal Data Warehouse

A local-first personal data warehouse: ingest activity from external sources
(GitHub, Google Calendar), store raw data in PostgreSQL, transform it into
analytics-ready models with dbt, and expose metrics through a dashboard and a
natural-language AI interface.

This is a portfolio-quality data-engineering project demonstrating API
ingestion, ELT pipelines, PostgreSQL modeling, dbt transformations, incremental
+ idempotent loading, observability, and a layered architecture. See
[`spec.md`](./spec.md) for the full specification.

> **Status (this milestone):** the foundation is in place — Dockerized
> PostgreSQL, raw schema + migrations, a synthetic data generator that stands
> in for the connector layer, and the full dbt transform path (staging →
> intermediate → marts + tests). The complete pipeline runs end-to-end on
> **synthetic data with no external credentials**. Real connectors, Dagster,
> the API, dashboard, and AI layer are deferred to later milestones.

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
make setup     # enable docker compose, create .env, install deps, make test db
make up        # start PostgreSQL
make sync      # migrate -> seed synthetic data -> build dbt models + tests
make status    # show recent pipeline runs
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
| `make test`   | run pytest (unit + integration)                        |
| `make psql`   | open a psql session                                     |
| `make status` | show recent pipeline runs                              |

## Environment variables

Copy `.env.example` to `.env` (done by `make setup`). Only `DATABASE_URL`
(and the `POSTGRES_*` vars it derives from) are required for the synthetic
pipeline. GitHub/Google/LLM credentials are needed only when the corresponding
connectors are enabled in later milestones. **Never commit `.env`.**

The app fails with a clear configuration error if required variables are
missing (spec §7).

## How ingestion works

Each connector implements a consistent interface (`fetch`, `normalize`, `load`)
and is isolated, testable, supports incremental ingestion, and is idempotent
(spec §9). Raw tables enforce natural keys with unique constraints and loaders
upsert via `ON CONFLICT`, so re-running a sync never duplicates rows (spec §12,
§13).

For this milestone, the **synthetic generator** (`ingestion/src/pdw/synthetic/`)
stands in for the connector layer: it produces realistic repositories, commits,
and calendar events and loads them into the raw tables exactly as a real
connector would, so the dbt models work identically against synthetic or real
data.

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