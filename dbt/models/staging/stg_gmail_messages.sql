-- Staging: Gmail messages — metadata only (spec §3, §14, §23).
-- From/To/Subject/Date headers + the Gmail snippet preview, never the body.
-- `date` is the server receive time from Gmail's internalDate. Natural key is
-- (source, source_id) where source_id is the Gmail message id.
select
    {{ surrogate_key(['source', 'source_id']) }} as message_key,
    source,
    source_id,
    thread_id::text as thread_id,
    sender::text as sender,
    recipients::text as recipients,
    subject::text as subject,
    date::timestamptz as date,
    snippet::text as snippet
from {{ source('raw', 'raw_gmail_messages') }}