-- 0004_gmail.sql — raw table for Gmail messages (spec §3, §8, §13, §23).
-- Metadata only: From/To/Subject/Date headers + the Gmail snippet preview, NEVER
-- the message body (spec §23 sensitive). Natural key is (source, source_id) where
-- source_id is the Gmail message id; upserts target that UK.
-- `date` is the server receive time from Gmail's internalDate (epoch ms). Gmail
-- messages are immutable, so `updated_at` is a row-timestamp (last touched), not
-- a source field (the commits/repos/calendar convention), set to now() on upsert.

CREATE TABLE IF NOT EXISTS raw_gmail_messages (
    source          text        NOT NULL,
    source_id       text        NOT NULL,           -- Gmail message id
    thread_id       text,
    sender          text,                           -- From header
    recipients      text,                           -- To header
    subject         text,
    date            timestamptz,                     -- internalDate (receive time)
    snippet         text,                           -- ~200-char preview, NOT the body
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    raw_payload     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT raw_gmail_messages_uk UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS raw_gmail_messages_date_idx
    ON raw_gmail_messages (date DESC);