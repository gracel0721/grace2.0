-- Mart: pull request fact, resolving repository_key via the staging repo model.
-- repository_key is the same surrogate used in dim_repository, so the
-- relationships test (fct_pull_requests.repository_key -> dim_repository) holds.
select
    p.pr_key,
    r.repository_key,
    p.number,
    p.title,
    p.state,
    p.author,
    p.created_at,
    p.updated_at,
    p.closed_at,
    p.merged_at,
    p.is_draft,
    p.comments_count
from {{ ref('stg_github_pull_requests') }} p
left join {{ ref('stg_github_repositories') }} r
    on p.repository_source_id = r.source_id