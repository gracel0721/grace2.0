-- Staging: GitHub repositories (spec §14).
-- Rename, type-cast, standardize timestamps; keep raw payload available.
select
    {{ surrogate_key(['source', 'source_id']) }} as repository_key,
    source,
    source_id,
    github_repository_id::bigint as github_repository_id,
    name::text as name,
    owner::text as owner,
    full_name::text as full_name,
    language::text as language,
    created_at::timestamptz as created_at,
    archived::boolean as archived,
    ingested_at::timestamptz as ingested_at,
    updated_at::timestamptz as updated_at
from {{ source('raw', 'raw_github_repositories') }}