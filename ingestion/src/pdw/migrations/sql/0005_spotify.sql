-- 0005_spotify.sql — raw table for Spotify recently-played tracks (spec §8, §13).
-- One row per play; natural key is (source, source_id) where source_id is
-- "{track_id}:{played_at_iso}" — the same track played at different times is a
-- distinct play (recently-played items carry no own id). The incremental cursor
-- is `played_at` expressed as epoch MILLISECONDS (Spotify's `after` param is ms).
-- `updated_at` is a row-timestamp (plays are immutable; set to now() on upsert).

CREATE TABLE IF NOT EXISTS raw_spotify_plays (
    source          text        NOT NULL,
    source_id       text        NOT NULL,           -- "{track_id}:{played_at}"
    played_at       timestamptz,
    track_id        text,
    track_name      text,
    artists         text,                           -- comma-joined names
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    raw_payload     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT raw_spotify_plays_uk UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS raw_spotify_plays_played_at_idx
    ON raw_spotify_plays (played_at DESC);