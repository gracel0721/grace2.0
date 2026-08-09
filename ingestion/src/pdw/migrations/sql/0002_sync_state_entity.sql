-- 0002_sync_state_entity.sql — per-entity incremental cursors (spec §12).
-- sync_state previously keyed on (connector) alone, which only allowed one
-- cursor per connector. Real connectors need a cursor per entity (e.g. one
-- per GitHub repository) so incremental syncs can resume independently. We add
-- an explicit, NOT NULL entity_key (no default — callers must name it) and
-- switch the primary key to the composite (connector, entity_key).

ALTER TABLE sync_state ADD COLUMN IF NOT EXISTS entity_key text;

-- Backfill any rows created before this migration (the synthetic loader uses
-- entity_key = 'all').
UPDATE sync_state SET entity_key = 'all' WHERE entity_key IS NULL;

ALTER TABLE sync_state ALTER COLUMN entity_key SET NOT NULL;

-- Replace the single-column primary key with the composite key.
ALTER TABLE sync_state DROP CONSTRAINT IF EXISTS sync_state_pkey;
ALTER TABLE sync_state ADD PRIMARY KEY (connector, entity_key);