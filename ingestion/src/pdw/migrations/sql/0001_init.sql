-- 0001_init.sql — raw + operational tables (spec §8, §12, §13, §24).
-- Raw tables preserve source payloads as JSONB with minimal transformation.
-- Natural keys are enforced with unique constraints so loaders can upsert
-- idempotently via ON CONFLICT (spec §13).

-- ============================================================================
-- Raw: GitHub repositories
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw_github_repositories (
    source                 text        NOT NULL,
    source_id              text        NOT NULL,
    github_repository_id   bigint,
    name                   text,
    owner                  text,
    full_name              text,
    language               text,
    created_at             timestamptz,
    archived               boolean,
    ingested_at            timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    raw_payload            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT raw_github_repositories_uk UNIQUE (source, source_id)
);

-- ============================================================================
-- Raw: GitHub commits
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw_github_commits (
    source                text        NOT NULL,
    source_id             text        NOT NULL,
    repository_source_id  text,
    commit_sha            text,
    author_name           text,
    author_email          text,
    committed_at          timestamptz,
    additions             integer,
    deletions             integer,
    message               text,
    ingested_at           timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    raw_payload           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT raw_github_commits_uk UNIQUE (source, source_id)
);

-- ============================================================================
-- Raw: Calendar events
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw_calendar_events (
    source            text        NOT NULL,
    calendar_id       text        NOT NULL,
    source_id         text        NOT NULL,
    title             text,
    start_at          timestamptz,
    end_at            timestamptz,
    timezone          text,
    attendees_count   integer,
    status            text,
    category          text,
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    raw_payload       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT raw_calendar_events_uk UNIQUE (source, calendar_id, source_id)
);

-- ============================================================================
-- Operational: pipeline run audit (spec §24)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id            uuid        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    source            text        NOT NULL,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL,
    records_fetched   integer     NOT NULL DEFAULT 0,
    records_inserted  integer     NOT NULL DEFAULT 0,
    records_updated   integer     NOT NULL DEFAULT 0,
    records_failed    integer     NOT NULL DEFAULT 0,
    error_message     text
);

CREATE INDEX IF NOT EXISTS pipeline_runs_source_idx
    ON pipeline_runs (source, started_at DESC);

-- ============================================================================
-- Operational: incremental sync checkpoints (spec §12)
-- ============================================================================
CREATE TABLE IF NOT EXISTS sync_state (
    connector             text        PRIMARY KEY,
    last_successful_sync  timestamptz,
    last_cursor           text,
    source_updated_at     timestamptz,
    updated_at            timestamptz NOT NULL DEFAULT now()
);