-- 0003_github_prs_issues.sql — raw tables for GitHub PRs + issues (spec §8, §13).
-- Both come from GET /repos/{owner}/{repo}/issues, split on the `pull_request`
-- key. Natural key is (source, source_id=node_id); upserts target that UK.
-- Additions/deletions are not fetched (the list endpoint omits them, like commits).

-- ============================================================================
-- Raw: GitHub pull requests
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw_github_pull_requests (
    source                text        NOT NULL,
    source_id             text        NOT NULL,           -- node_id
    repository_source_id  text,                           -- repo full_name
    number                integer,
    title                 text,
    state                 text,
    author                text,
    created_at            timestamptz,
    updated_at            timestamptz,
    closed_at             timestamptz,
    merged_at             timestamptz,
    is_draft              boolean,
    comments_count        integer,
    ingested_at           timestamptz NOT NULL DEFAULT now(),
    raw_payload           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT raw_github_pull_requests_uk UNIQUE (source, source_id)
);

-- ============================================================================
-- Raw: GitHub issues
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw_github_issues (
    source                text        NOT NULL,
    source_id             text        NOT NULL,           -- node_id
    repository_source_id  text,                           -- repo full_name
    number                integer,
    title                 text,
    state                 text,
    state_reason          text,
    author                text,
    created_at            timestamptz,
    updated_at            timestamptz,
    closed_at             timestamptz,
    comments_count        integer,
    ingested_at           timestamptz NOT NULL DEFAULT now(),
    raw_payload           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT raw_github_issues_uk UNIQUE (source, source_id)
);