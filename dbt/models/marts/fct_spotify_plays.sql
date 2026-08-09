-- Mart: spotify play fact — one row per track play (spec §15).
select
    play_key,
    played_at,
    track_id,
    track_name,
    artists
from {{ ref('stg_spotify_plays') }}