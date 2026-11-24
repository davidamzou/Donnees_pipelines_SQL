-- Transformation réutilisable : chaque observation d'offre reçoit les libellés
-- produit, catégorie et fournisseur.
-- Grain inchangé : (offer_id, observed_on). Les trois jointures sont n-1 sur des
-- clés uniques (testées en staging) : elles ne peuvent pas multiplier les lignes.
-- Jointures internes : la clé étrangère produit et la référence fournisseur
-- imposées par le chargeur garantissent qu'aucune observation n'est perdue
-- (contrôlé par tests/assert_volumes_offres.sql).
select
    o.offer_id,
    o.observed_on,
    o.supplier_id,
    s.supplier_name,
    o.product_id,
    p.sku,
    p.product_name,
    p.category_id,
    c.category_name,
    o.price_cents,
    o.price_eur,
    o.currency,
    o.available_units
from {{ ref('stg_fournisseur__offres') }}        as o
join {{ ref('stg_fournisseur__fournisseurs') }}  as s on s.supplier_id = o.supplier_id
join {{ ref('stg_nova__products') }}             as p on p.product_id  = o.product_id
join {{ ref('stg_nova__categories') }}           as c on c.category_id = p.category_id
