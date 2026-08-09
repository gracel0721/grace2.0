-- Staging: Spotify recently-played tracks (spec §14).
-- One row per play; natural key is (source, source_id) where source_id is
-- "{track_id}:{played_at_iso}" — the same track at different times is distinct.
-- `played_at` is the listen timestamp (tz-aware).
select
    {{ surrogate_key(['source', 'source_id']) }} as play_key,
    source,
    source_id,
    played_at::timestamptz as played_at,
    track_id::text as track_id,
    track_name::text as track_name,
    artists::text as artists
from {{ source('raw', 'raw_spotify_plays') }}