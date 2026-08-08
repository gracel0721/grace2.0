-- Mart: repository dimension (spec §15).
select
    repository_key,
    github_repository_id,
    name,
    owner,
    language,
    created_at,
    archived
from {{ ref('stg_github_repositories') }}