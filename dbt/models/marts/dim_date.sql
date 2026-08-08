-- Mart: date dimension spanning all observed activity (spec §15).
with bounds as (
    select
        min(activity_date) as min_date,
        max(activity_date) as max_date
    from (
        select committed_at::date as activity_date from {{ ref('stg_github_commits') }}
        union all
        select start_at::date as activity_date from {{ ref('stg_calendar_events') }}
    ) combined
),
spine as (
    select generate_series(min_date, max_date, '1 day')::date as date
    from bounds
)
select
    date,
    trim(to_char(date, 'Day')) as day_of_week,
    to_char(date, 'IYYY-IW') as week,
    to_char(date, 'YYYY-MM') as month,
    extract(quarter from date)::integer as quarter,
    extract(year from date)::integer as year,
    (extract(dow from date)::integer in (0, 6)) as is_weekend
from spine