-- Mart: month-over-month summary (spec §15, §20).
with monthly_commits as (
    select
        to_char(committed_at, 'YYYY-MM') as month,
        count(*) as commits,
        count(distinct repository_key) as active_repos
    from {{ ref('fct_commits') }}
    group by 1
),
meetings as (
    select
        to_char(start_at, 'YYYY-MM') as month,
        sum(duration_minutes) as meeting_minutes,
        count(*) as meeting_count
    from {{ ref('fct_calendar_events') }}
    where category = 'meeting'
    group by 1
),
active_days as (
    select
        to_char(date, 'YYYY-MM') as month,
        count(distinct case when commit_count > 0 then date end) as active_days
    from {{ ref('mart_daily_activity') }}
    group by 1
)
select
    coalesce(c.month, m.month, d.month) as month,
    coalesce(c.commits, 0) as commits,
    coalesce(c.active_repos, 0) as active_repos,
    coalesce(m.meeting_minutes, 0) as meeting_minutes,
    coalesce(m.meeting_count, 0) as meeting_count,
    coalesce(d.active_days, 0) as active_days
from monthly_commits c
full outer join meetings m on c.month = m.month
full outer join active_days d on coalesce(c.month, m.month) = d.month