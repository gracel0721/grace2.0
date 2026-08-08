-- Intermediate: calendar activity grouped by date and category.
select
    start_at::date as activity_date,
    category,
    sum(duration_minutes) as minutes,
    count(*) as event_count
from {{ ref('stg_calendar_events') }}
group by 1, 2