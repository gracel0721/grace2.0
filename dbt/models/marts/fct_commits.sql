-- Mart: commit fact, resolving repository_key via the staging repo model.
-- repository_key is the same surrogate used in dim_repository, so the
-- relationships test (fct_commits.repository_key -> dim_repository) holds.
select
    c.commit_key,
    r.repository_key,
    c.commit_id,
    c.author,
    c.committed_at,
    c.additions,
    c.deletions
from {{ ref('stg_github_commits') }} c
left join {{ ref('stg_github_repositories') }} r
    on c.repository_source_id = r.source_id