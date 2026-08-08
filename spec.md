# Project 4: Personal Data Warehouse

## 1. Overview

Build a local-first personal data warehouse that ingests data from a small number of external sources, stores raw data in PostgreSQL, transforms it into analytics-ready models with dbt, and exposes useful metrics through a simple dashboard and natural-language AI interface.

This is intentionally a portfolio-quality data engineering project, not a generic productivity app.

The system should demonstrate:

- API ingestion
- ETL/ELT pipelines
- PostgreSQL data modeling
- dbt transformations and tests
- Incremental loading
- Idempotent pipelines
- Scheduling/orchestration
- Data quality checks
- Analytics
- Basic observability
- LLM-powered querying/summarization as an optional final layer
- Dockerized local development
- Clean software engineering practices

The project should be designed so that additional data sources can be added without rewriting the pipeline architecture.

---

## 2. Product Goal

Create a system that answers questions about the user's activity across multiple services.

Example questions:

- How many hours did I spend working on each project this month?
- Which projects have I worked on recently?
- How many commits did I make this week?
- What languages have I been using most?
- How has my activity changed month over month?
- Which projects have become inactive?
- What did I accomplish this week?
- What work consumed most of my time?
- Which days were most/least active?

The system should separate:

1. **Raw ingestion**
2. **Transformation**
3. **Analytics**
4. **Presentation / AI**

Do not mix these layers together.

---

# 3. Scope

## MVP Data Sources

Implement exactly two initial data sources:

1. GitHub
2. Calendar

Do not implement additional integrations during the MVP.

The architecture must make adding future sources straightforward.

Potential future sources:

- GitHub pull requests
- GitHub issues
- Notion
- browser bookmarks
- job applications
- Spotify
- Linear
- Slack
- email metadata
- personal notes

These should NOT be implemented unless explicitly requested later.

---

# 4. High-Level Architecture

```text
                 External APIs
                 /           \
                /             \
         GitHub API        Calendar API
              |                 |
              v                 v
        +-----------------------------+
        |        Ingestion Layer      |
        |                             |
        | Python connectors            |
        +-------------+---------------+
                      |
                      v
             +----------------+
             | Raw PostgreSQL |
             |                |
             | raw_* tables   |
             +--------+-------+
                      |
                      v
                  dbt models
                      |
          +-----------+-----------+
          |                       |
          v                       v
   staging models          intermediate models
                                  |
                                  v
                           analytics models
                                  |
                                  v
                         +------------------+
                         | Dashboard / API  |
                         +------------------+
                                  |
                                  v
                         Optional AI Layer
```

---

# 5. Technology Stack

Use the following stack unless there is a compelling technical reason not to.

## Core

- Python 3.12+
- PostgreSQL 16+
- dbt Core
- Docker / Docker Compose
- FastAPI
- pytest

## Data

- SQLAlchemy or psycopg
- Pydantic
- pandas or Polars where useful

Prefer SQL/dbt for transformations rather than performing analytics transformations in Python.

## Scheduling

Use one of:

- Dagster
- Prefect
- Apache Airflow

Prefer **Dagster** for this project because it provides a good balance of modern developer experience, explicit assets, observability, and portfolio value.

Do not introduce a heavyweight distributed orchestration system unless necessary.

## Dashboard

Use a lightweight frontend.

Preferred:

- Next.js + TypeScript

Alternative if keeping the project smaller:

- FastAPI + server-rendered templates

The UI should not become the main focus of the project.

## AI

Optional MVP+ feature:

- OpenAI-compatible LLM API
- structured tool/function calls
- natural-language analytics queries

Do not build an autonomous agent initially.

---

# 6. Repository Structure

Use a monorepo with a clear separation between application code and dbt.

Suggested structure:

```text
personal-data-warehouse/
├── README.md
├── SPEC.md
├── docker-compose.yml
├── .env.example
├── Makefile
│
├── apps/
│   ├── api/
│   │   ├── pyproject.toml
│   │   └── src/
│   │       └── ...
│   │
│   └── web/
│       ├── package.json
│       └── ...
│
├── ingestion/
│   ├── pyproject.toml
│   ├── src/
│   │   ├── connectors/
│   │   │   ├── github.py
│   │   │   └── calendar.py
│   │   ├── pipeline/
│   │   │   ├── runner.py
│   │   │   └── checkpoints.py
│   │   └── ...
│   └── tests/
│
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml.example
│   ├── models/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   └── marts/
│   ├── seeds/
│   ├── snapshots/
│   └── tests/
│
├── infra/
│   └── ...
│
└── docs/
    ├── architecture.md
    └── data-model.md
```

The exact structure may be adjusted if a simpler organization improves maintainability.

---

# 7. Environment Configuration

Provide `.env.example`.

Required configuration should include:

```text
DATABASE_URL=
GITHUB_TOKEN=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
LLM_API_KEY=
```

Only variables required for the enabled functionality should be mandatory at runtime.

Never commit secrets.

The application should fail with a clear configuration error rather than an obscure stack trace.

---

# 8. Raw Data Layer

The raw layer should preserve data from external APIs with minimal transformation.

Use tables such as:

```text
raw_github_events
raw_github_commits
raw_github_repositories

raw_calendar_events
```

Each raw record should include metadata such as:

```text
source
source_id
ingested_at
updated_at
raw_payload
```

Store the original API payload as JSONB where practical.

The raw layer exists so that downstream models can be rebuilt without repeatedly hitting external APIs.

---

# 9. Ingestion Architecture

Every connector should implement a consistent interface.

Conceptually:

```python
class Connector:
    def fetch(self, start, end):
        ...

    def normalize(self, records):
        ...

    def load(self, records):
        ...
```

The exact interface can differ if a better design emerges.

The important requirement is that connectors:

- are isolated
- are testable
- support incremental ingestion
- are idempotent
- do not contain analytics/business logic

---

# 10. GitHub Connector

The GitHub connector should initially ingest:

- repositories
- commits
- repository metadata

Optional if easy:

- pull requests

Do not make pull requests a hard MVP dependency.

## GitHub metrics

The warehouse should eventually support:

- commits per day
- commits per week
- commits per repository
- active repositories
- languages used
- activity by month
- first/last activity date
- repository activity trends

Do not equate commit count directly with productivity. Present it as an activity metric.

---

# 11. Calendar Connector

Use Google Calendar initially.

Ingest:

- event ID
- calendar ID
- title
- description if available
- start time
- end time
- timezone
- attendees count if available
- event status
- event type/category if available

Avoid storing unnecessary sensitive event details.

The warehouse should support:

- total scheduled hours
- meeting hours
- meetings per day/week
- meeting hours by category
- time distribution throughout the week

Provide a simple mechanism for categorizing calendar events.

For example:

```text
work
personal
learning
meeting
other
```

Do not require an ML classifier for categorization in the MVP.

---

# 12. Incremental Loading

The pipeline must not re-download everything on every run.

Use incremental ingestion based on:

- timestamps
- API pagination
- source IDs
- checkpoints

Each connector should maintain enough state to determine where the previous successful ingestion ended.

Example:

```text
last_successful_sync
last_cursor
source_updated_at
```

The pipeline must be safe to run twice.

Running:

```text
sync → sync
```

should not create duplicate records.

---

# 13. Idempotency

All ingestion operations must be idempotent.

Use source-system identifiers as natural keys where possible.

Example:

```text
github repository:
(source, source_id)

calendar event:
(source, calendar_id, source_id)
```

Use PostgreSQL upserts where appropriate.

Do not rely on application-level "check then insert" logic when a database constraint can enforce uniqueness.

---

# 14. dbt Layering

Use a standard dbt architecture.

```text
raw
 ↓
staging
 ↓
intermediate
 ↓
marts
```

## Staging

Staging models should:

- rename columns
- normalize types
- flatten relevant JSON
- standardize timestamps
- clean source-specific inconsistencies

Example:

```text
stg_github_commits
stg_github_repositories
stg_calendar_events
```

## Intermediate

Intermediate models combine sources and establish reusable concepts.

Example:

```text
int_daily_activity
int_project_activity
int_calendar_activity
```

## Marts

Create analytics-focused models.

Example:

```text
fct_commits
fct_calendar_events
fct_daily_activity

dim_date
dim_repository
dim_project

mart_productivity_daily
mart_project_activity
mart_monthly_summary
```

---

# 15. Data Model

Create a documented star-schema-like analytical model.

At minimum:

## dim_date

```text
date
day_of_week
week
month
quarter
year
is_weekend
```

## dim_repository

```text
repository_key
github_repository_id
name
owner
language
created_at
archived
```

## fct_commits

```text
commit_key
repository_key
commit_id
author
committed_at
additions
deletions
```

## fct_calendar_events

```text
event_key
calendar_event_id
start_at
end_at
duration_minutes
category
```

## mart_daily_activity

```text
date
commit_count
active_repositories
meeting_minutes
meeting_count
```

Additional dimensions/facts may be added as needed.

---

# 16. dbt Tests

Use dbt tests extensively.

At minimum:

- unique
- not_null
- relationships
- accepted_values where appropriate

Examples:

```text
repository ID must be unique
commit ID must be unique
event ID must be unique
repository_key must reference dim_repository
calendar category must be one of allowed categories
```

Add custom data-quality tests for important business rules.

Examples:

```text
meeting duration cannot be negative

commit timestamp cannot be in an impossible range

daily activity should not have duplicate dates
```

---

# 17. Scheduling

Create scheduled jobs for:

```text
GitHub ingestion
Calendar ingestion
dbt transformations
data-quality tests
```

A sensible development schedule:

```text
Every 1-6 hours:
    ingest external data

After successful ingestion:
    dbt staging
    dbt intermediate
    dbt marts
    dbt tests
```

The exact frequency should be configurable.

Do not make the system dependent on a continuously running scheduler during local development.

Provide a manual command:

```bash
make sync
```

that performs a complete ingestion + transformation run.

---

# 18. CLI

Provide a useful CLI for operating the system.

Example:

```bash
make setup
make up
make migrate
make sync
make test
make dbt
make down
```

Or a dedicated CLI:

```bash
pdw sync
pdw sync github
pdw sync calendar
pdw dbt
pdw status
pdw health
```

The CLI should provide useful progress/error output.

---

# 19. API

Create a small FastAPI service exposing analytics.

Example endpoints:

```text
GET /health

GET /api/activity/daily
GET /api/activity/weekly
GET /api/activity/monthly

GET /api/projects
GET /api/projects/{id}

GET /api/github/activity
GET /api/calendar/activity

GET /api/summary
```

Return typed Pydantic responses.

Do not expose raw source data through public endpoints unless necessary.

---

# 20. Dashboard

Build a simple dashboard.

Do not over-invest in visual design.

The dashboard should answer:

### Overview

```text
This week

Commits: 42
Repositories: 4
Meeting hours: 8.5
Active days: 5
```

### Activity

Graph:

```text
daily activity over time
```

### Projects

Table:

```text
Project       Last Active    Commits    Status
------------------------------------------------
project-a     today          21         active
project-b     3 days ago     12         active
project-c     24 days ago    4          stale
```

### Calendar

Show:

- meeting hours
- meetings per day
- weekly distribution

### Trends

Show month-over-month changes.

---

# 21. AI Layer

This should be implemented only after the data pipeline is reliable.

The AI layer should NOT directly query arbitrary database tables using unrestricted generated SQL in the first version.

Instead expose a small set of safe analytics tools/functions.

Example:

```text
get_daily_activity(start_date, end_date)

get_project_activity(project_id, start_date, end_date)

get_monthly_summary(month)

get_meeting_statistics(start_date, end_date)
```

The LLM chooses the appropriate tool.

Example:

User:

> What did I spend most of my time on last month?

Flow:

```text
User question
    ↓
LLM
    ↓
get_monthly_summary()
    ↓
structured analytics
    ↓
LLM
    ↓
natural language response
```

This is safer and easier to debug than allowing arbitrary SQL generation.

---

# 22. AI Summary Example

The system should be capable of producing:

```text
August Summary

You were active on 5 projects.

Your most active project was personal-data-warehouse,
with 47% of your recorded development activity.

You had 31.5 hours of scheduled meetings.

Development activity increased 14% compared with July.

Your activity was highest on Tuesdays and lowest on Fridays.

Note:
These metrics represent recorded GitHub and calendar
activity and should not be interpreted as a direct measure
of productivity.
```

Avoid making unsupported conclusions.

The AI should distinguish:

```text
observed data
vs.
interpretation
```

---

# 23. Privacy

Treat this as a personal-data application.

Requirements:

- local-first development
- secrets only in environment variables
- no telemetry
- no unnecessary external analytics
- no raw calendar data sent to an LLM
- AI layer should receive aggregated analytics whenever possible
- document what data leaves the machine
- provide a way to delete imported data

Calendar data should be treated as sensitive.

Do not store OAuth tokens in PostgreSQL unless there is a strong reason.

---

# 24. Observability

Implement basic pipeline observability.

Track:

```text
pipeline run
source
started_at
finished_at
status
records_fetched
records_inserted
records_updated
records_failed
error_message
```

Create a table:

```text
pipeline_runs
```

This should allow:

```bash
pdw status
```

to show:

```text
GitHub       SUCCESS   12 min ago   143 records
Calendar     SUCCESS   12 min ago   28 records
dbt          SUCCESS   11 min ago   17 models
Tests        SUCCESS   11 min ago   42 tests
```

---

# 25. Error Handling

External APIs fail.

Design for:

- rate limits
- expired OAuth tokens
- network failures
- pagination errors
- malformed records
- partial failures

A failed GitHub sync should not corrupt existing data.

A failed calendar sync should not prevent already-ingested GitHub data from being usable.

Make pipeline stages restartable.

---

# 26. Testing

Write tests at multiple levels.

## Unit tests

Test:

- connector normalization
- date handling
- pagination
- category mapping
- transformation logic

## Integration tests

Test:

```text
API → ingestion → PostgreSQL
```

Use a test database.

## dbt tests

Run all dbt tests as part of CI.

## End-to-end test

Provide a small fixture dataset and verify:

```text
fixture data
    ↓
raw tables
    ↓
dbt
    ↓
analytics tables
    ↓
API response
```

---

# 27. Local Development

Everything should run locally with Docker Compose.

At minimum:

```text
postgres
api
web
dagster
```

Only add separate services when required.

Provide:

```bash
make up
```

and the project should become usable with minimal setup.

Provide:

```bash
make seed
```

to load fake development data.

This is important because developers should be able to run the project without connecting personal accounts.

---

# 28. Demo Dataset

Create realistic synthetic data.

The demo dataset should include:

- multiple repositories
- several weeks/months of commits
- multiple projects
- calendar events
- different meeting categories
- active and inactive projects

The dashboard should look meaningful without any real personal data.

---

# 29. CI

Set up GitHub Actions.

Pipeline:

```text
push / pull request
        ↓
lint
        ↓
unit tests
        ↓
integration tests
        ↓
dbt build
        ↓
dbt tests
```

Use appropriate Python linting/formatting tools such as:

- Ruff
- pytest
- mypy if practical

Do not introduce excessive tooling.

---

# 30. Documentation

README.md should explain:

1. What the project does
2. Architecture
3. Tech stack
4. Local setup
5. Environment variables
6. How ingestion works
7. Data model
8. dbt architecture
9. How to run tests
10. How to add a connector

Create:

```text
docs/architecture.md
docs/data-model.md
```

Include architecture diagrams using Mermaid where helpful.

---

# 31. Definition of Done — MVP

The MVP is complete when:

- [ ] PostgreSQL runs through Docker Compose
- [ ] GitHub connector works
- [ ] Calendar connector works
- [ ] Raw data is stored in PostgreSQL
- [ ] Ingestion is incremental
- [ ] Ingestion is idempotent
- [ ] dbt staging models exist
- [ ] dbt intermediate models exist
- [ ] dbt marts exist
- [ ] dbt tests exist
- [ ] Pipeline runs can be inspected
- [ ] FastAPI exposes analytics
- [ ] Dashboard displays meaningful metrics
- [ ] Synthetic demo data exists
- [ ] Full system works without real credentials using demo data
- [ ] Tests pass
- [ ] README documents setup and architecture
- [ ] CI runs successfully

---

# 32. Post-MVP Roadmap

Do NOT implement these during the MVP.

Potential future phases:

## Phase 2 — More data

- GitHub PRs
- GitHub issues
- Notion
- job applications
- browser bookmarks

## Phase 3 — Better analytics

- project classification
- activity scoring
- anomaly detection
- productivity trends
- cross-source correlation

## Phase 4 — AI

- natural-language analytics
- weekly summaries
- monthly reports
- question answering
- proactive insights

## Phase 5 — Personal Knowledge Graph

Connect:

```text
Person
  ↓
Project
  ↓
Repository
  ↓
Commit
  ↓
Calendar Event
  ↓
Document
```

## Phase 6 — Developer OS

Integrate this project with the other three projects:

```text
explain-error
      │
      ↓
developer activity
      │
      ↓
personal data warehouse
      │
      ├───────────────┐
      ↓               ↓
codebase RAG       personal RAG
      │               │
      └───────┬───────┘
              ↓
         AI interface
```

---

# 33. Engineering Principles

Follow these principles throughout implementation.

### Keep ingestion and transformation separate.

Bad:

```text
API → Python → fully transformed analytics table
```

Preferred:

```text
API → raw → dbt → analytics
```

### Prefer database constraints over application assumptions.

### Prefer idempotent operations.

### Prefer explicit data models over unstructured JSON once data reaches the analytics layer.

### Keep connectors independent.

### Don't over-engineer the MVP.

### Don't add Kubernetes.

### Don't add Kafka.

### Don't add microservices.

### Don't add a vector database.

### Don't build an elaborate AI agent.

The goal is to demonstrate solid data engineering fundamentals first.

---

# 34. Suggested Implementation Order

Implement in this exact general sequence:

## Step 1

Initialize repository.

Set up:

- Python
- Docker Compose
- PostgreSQL
- Makefile
- linting
- tests

## Step 2

Create database schema and migrations.

## Step 3

Implement synthetic data generator.

Get the complete pipeline working with fake data first.

## Step 4

Implement GitHub connector.

## Step 5

Implement Calendar connector.

## Step 6

Implement incremental/idempotent ingestion.

## Step 7

Set up dbt.

Implement:

```text
staging
→ intermediate
→ marts
```

## Step 8

Add dbt tests.

## Step 9

Add Dagster orchestration.

## Step 10

Build FastAPI analytics endpoints.

## Step 11

Build simple dashboard.

## Step 12

Add pipeline observability.

## Step 13

Add CI.

## Step 14

Only after everything above works, add the AI layer.

---

# 35. Claude Code Instructions

When implementing this specification:

1. Read the entire SPEC.md before making architectural decisions.
2. Do not implement post-MVP features prematurely.
3. Work incrementally.
4. Keep commits/features logically separated.
5. Run tests after meaningful changes.
6. Prefer simple solutions over abstractions that aren't currently needed.
7. Do not invent external API behavior. Consult official documentation when necessary.
8. Never hard-code credentials.
9. Never commit `.env`.
10. Preserve idempotency.
11. Add tests alongside new functionality.
12. Update documentation when architecture changes.
13. Do not silently change the project scope.
14. If a requirement is ambiguous, choose the simplest implementation consistent with this specification.
15. If an architectural change would materially affect the specification, explain the tradeoff before implementing it.

## First task

Before writing application code:

1. Inspect the repository.
2. Create a concise implementation plan.
3. Identify missing dependencies/tools.
4. Set up the project skeleton.
5. Implement PostgreSQL + Docker Compose.
6. Implement synthetic seed data.
7. Prove the complete local pipeline works with synthetic data.
8. Then proceed to the first real connector.

The system should always have a working, testable state as development progresses.
