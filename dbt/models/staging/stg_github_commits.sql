-- Staging: GitHub commits (spec §14).
select
    {{ surrogate_key(['source', 'source_id']) }} as commit_key,
    source,
    source_id,
    repository_source_id::text as repository_source_id,
    commit_sha::text as commit_id,
    author_name::text as author,
    author_email::text as author_email,
    committed_at::timestamptz as committed_at,
    additions::integer as additions,
    deletions::integer as deletions,
    message::text as message
from {{ source('raw', 'raw_github_commits') }}