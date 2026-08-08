-- Intermediate: per-repository (project) activity and staleness.
-- A project is "active" if its most recent commit is within 14 days of the
-- latest commit in the dataset (the data's "as-of" date). For the MVP a
-- project is modeled 1:1 with a repository (spec §15 simplification).
with latest as (
    select max(committed_at) as as_of from {{ ref('stg_github_commits') }}
)
select
    r.repository_key,
    r.name,
    max(c.committed_at) as last_active,
    count(c.commit_id) as commit_count,
    case
        when max(c.committed_at) is null then 'inactive'
        when max(c.committed_at) >= (select as_of from latest) - interval '14 days'
            then 'active'
        else 'stale'
    end as status
from {{ ref('stg_github_repositories') }} r
left join {{ ref('stg_github_commits') }} c
    on c.repository_source_id = r.source_id
group by 1, 2