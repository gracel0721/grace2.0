-- Mart: email message fact — one row per Gmail message, metadata only (spec §15, §23).
-- No body content is stored or modeled anywhere in the warehouse.
select
    message_key,
    thread_id,
    sender,
    recipients,
    subject,
    date,
    snippet
from {{ ref('stg_gmail_messages') }}