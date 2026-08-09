-- Mart: issue fact, resolving repository_key via the staging repo model.
-- repository_key is the same surrogate used in dim_repository, so the
-- relationships test (fct_issues.repository_key -> dim_repository) holds.
select
    i.issue_key,
    r.repository_key,
    i.number,
    i.title,
    i.state,
    i.state_reason,
    i.author,
    i.created_at,
    i.updated_at,
    i.closed_at,
    i.comments_count
from {{ ref('stg_github_issues') }} i
left join {{ ref('stg_github_repositories') }} r
    on i.repository_source_id = r.source_id