-- Staging: GitHub pull requests (spec §14).
-- PRs are fetched from the issues endpoint and split on the `pull_request` key
-- (every PR is an issue). Natural key is (source, source_id=node_id).
select
    {{ surrogate_key(['source', 'source_id']) }} as pr_key,
    source,
    source_id,
    repository_source_id::text as repository_source_id,
    number::integer as number,
    title::text as title,
    state::text as state,
    author::text as author,
    created_at::timestamptz as created_at,
    updated_at::timestamptz as updated_at,
    closed_at::timestamptz as closed_at,
    merged_at::timestamptz as merged_at,
    is_draft::boolean as is_draft,
    comments_count::integer as comments_count
from {{ source('raw', 'raw_github_pull_requests') }}