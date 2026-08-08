-- Mart: calendar event fact (spec §15).
select
    event_key,
    calendar_event_id,
    start_at,
    end_at,
    duration_minutes,
    category
from {{ ref('stg_calendar_events') }}