-- Grain : une catégorie ; parent_category_id nul pour une racine.
select
    category_id,
    category_name,
    parent_category_id
from {{ source('nova', 'categories') }}
