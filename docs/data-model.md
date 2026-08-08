# Data Model

A star-schema-like analytical model sits on top of the raw layer. Raw tables
preserve original API payloads as JSONB; dbt staging flattens and types them;
intermediate models join and standardize; marts expose analytics-ready facts
and dimensions (spec §8, §14, §15).

## Raw layer (ingested, minimal transformation)

All raw tables share metadata columns:

| column         | type        | notes                                   |
| -------------- | ----------- | --------------------------------------- |
| source         | text        | e.g. `github`, `calendar`, `synthetic`  |
| source_id      | text        | natural key from the source system      |
| ingested_at    | timestamptz | when we loaded the row                  |
| updated_at     | timestamptz | last upsert time                        |
| raw_payload    | jsonb       | original API payload                     |

- `raw_github_repositories` — unique `(source, source_id)`; extracted:
  `github_repository_id, name, owner, full_name, language, created_at, archived`.
- `raw_github_commits` — unique `(source, source_id)`; extracted:
  `repository_source_id, commit_sha, author_name, author_email, committed_at,
  additions, deletions, message`.
- `raw_calendar_events` — unique `(source, calendar_id, source_id)`; extracted:
  `calendar_id, title, start_at, end_at, timezone, attendees_count, status,
  category`.

Operational tables: `pipeline_runs` (run audit) and `sync_state` (incremental
checkpoints).

## Analytics layer (dbt)

### Dimensions

**dim_date** — generated spine covering all activity dates.

`date, day_of_week, week, month, quarter, year, is_weekend`

**dim_repository**

`repository_key, github_repository_id, name, owner, language, created_at, archived`

> **Simplification (MVP):** a "project" is modeled 1:1 with a repository. A
> separate `dim_project` that groups multiple repos is deferred to post-MVP
> project classification (spec §32 Phase 3).

### Facts

**fct_commits**

`commit_key, repository_key, commit_id, author, committed_at, additions, deletions`

**fct_calendar_events**

`event_key, calendar_event_id, start_at, end_at, duration_minutes, category`

### Marts

**mart_daily_activity**

`date, commit_count, active_repositories, meeting_minutes, meeting_count`

**mart_project_activity**

`repository_key, name, last_active, commit_count, status` (`active` if last
commit within 14 days, else `stale`)

**mart_monthly_summary**

`month, commits, active_repos, meeting_minutes, meeting_count, active_days`

## Calendar categories

Calendar events are categorized at load time (keyword rules in
`synthetic/categorize.py`) into the accepted set (spec §11):

`work, personal, learning, meeting, other`

The same rules will be reused by the real Calendar connector. dbt enforces the
set with an `accepted_values` test.

## Tests (spec §16)

- `unique` / `not_null` on `source_id`, `commit_id`, `event_id`,
  `repository_key`.
- `relationships`: `fct_commits.repository_key` → `dim_repository`.
- `accepted_values`: calendar `category`.
- Custom: no negative `duration_minutes`; no duplicate
  `mart_daily_activity.date`; `committed_at` within a plausible range.