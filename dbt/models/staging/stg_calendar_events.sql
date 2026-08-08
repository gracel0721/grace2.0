-- Staging: Calendar events (spec §14).
-- Compute duration_minutes here so downstream models stay simple.
select
    {{ surrogate_key(['source', 'calendar_id', 'source_id']) }} as event_key,
    source,
    calendar_id::text as calendar_id,
    source_id::text as calendar_event_id,
    title::text as title,
    start_at::timestamptz as start_at,
    end_at::timestamptz as end_at,
    timezone::text as timezone,
    attendees_count::integer as attendees_count,
    status::text as status,
    category::text as category,
    round(extract(epoch from (end_at - start_at)) / 60.0)::integer as duration_minutes
from {{ source('raw', 'raw_calendar_events') }}