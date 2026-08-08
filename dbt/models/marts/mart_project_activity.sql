-- Mart: per-project (repository) activity and status (spec §15, §20).
select
    repository_key,
    name,
    last_active,
    commit_count,
    status
from {{ ref('int_project_activity') }}