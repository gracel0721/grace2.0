{% macro surrogate_key(fields) -%}
  md5(
  {%- for f in fields -%}
    coalesce(cast({{ f }} as text), '')
    {%- if not loop.last %} || '|' || {% endif -%}
  {%- endfor -%}
  )
{%- endmacro %}