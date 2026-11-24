-- Grain : un produit du catalogue S2 (doublon brut du produit 3 déjà rejeté en S2).
select
    product_id,
    sku,
    product_name,
    category_id,
    first_listed_on
from {{ source('nova', 'products') }}
