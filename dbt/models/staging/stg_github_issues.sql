-- Staging: GitHub issues (spec §14).
-- Issues are items from the issues endpoint with no `pull_request` key.
-- Natural key is (source, source_id=node_id).
select
    {{ surrogate_key(['source', 'source_id']) }} as issue_key,
    source,
    source_id,
    repository_source_id::text as repository_source_id,
    number::integer as number,
    title::text as title,
    state::text as state,
    state_reason::text as state_reason,
    author::text as author,
    created_at::timestamptz as created_at,
    updated_at::timestamptz as updated_at,
    closed_at::timestamptz as closed_at,
    comments_count::integer as comments_count
from {{ source('raw', 'raw_github_issues') }}