-- Intermediate: daily activity combining GitHub commits and calendar meetings.
with commits as (
    select
        committed_at::date as activity_date,
        count(*) as commit_count,
        count(distinct repository_source_id) as active_repositories
    from {{ ref('stg_github_commits') }}
    group by 1
),
meetings as (
    select
        start_at::date as activity_date,
        sum(duration_minutes) as meeting_minutes,
        count(*) as meeting_count
    from {{ ref('stg_calendar_events') }}
    where category = 'meeting'
    group by 1
)
select
    coalesce(com.activity_date, mtg.activity_date) as activity_date,
    coalesce(com.commit_count, 0) as commit_count,
    coalesce(com.active_repositories, 0) as active_repositories,
    coalesce(mtg.meeting_minutes, 0) as meeting_minutes,
    coalesce(mtg.meeting_count, 0) as meeting_count
from commits com
full outer join meetings mtg on com.activity_date = mtg.activity_date