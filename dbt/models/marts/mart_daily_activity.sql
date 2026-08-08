-- Mart: daily activity over the full date spine (spec §15, §20).
-- Days with no activity show zeros, giving a continuous series for charts.
select
    d.date,
    coalesce(i.commit_count, 0) as commit_count,
    coalesce(i.active_repositories, 0) as active_repositories,
    coalesce(i.meeting_minutes, 0) as meeting_minutes,
    coalesce(i.meeting_count, 0) as meeting_count
from {{ ref('dim_date') }} d
left join {{ ref('int_daily_activity') }} i
    on d.date = i.activity_date