-- Use custom schema names verbatim rather than prefixing them with the target
-- schema (dbt's default concatenates target.schema + '_' + custom_schema). With
-- this override: staging -> `staging`, intermediate -> `intermediate`,
-- marts -> `analytics` (the custom schema set in dbt_project.yml).
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}