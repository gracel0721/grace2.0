-- Custom data-quality test (spec §16): meeting/event durations cannot be negative.
-- Any row returned is a failure.
select event_key
from {{ ref('fct_calendar_events') }}
where duration_minutes < 0