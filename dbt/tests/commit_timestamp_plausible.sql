-- Custom data-quality test (spec §16): commit timestamps must fall in a
-- plausible range (not in the future, not before 2000-01-01).
select commit_key
from {{ ref('fct_commits') }}
where committed_at > now() or committed_at < timestamp '2000-01-01'