-- Premier mart : couverture fournisseurs et écart avec le prix de vente.
-- Grain : UN PRODUIT DU CATALOGUE (24 lignes), y compris les produits sans offre.
-- Le catalogue est la table de départ ; offres et ventes y sont rattachées par
-- jointures externes APRÈS agrégation par produit, donc 0 ou 1 ligne chacune :
-- aucune multiplication possible.
-- Matérialisé en table : lu par la BI (S6), reconstruit à chaque dbt run.
with offres_par_produit as (
    select
        product_id,
        count(*)                                        as nb_active_offers,
        count(distinct supplier_id)                     as nb_suppliers,
        min(price_cents)                                as best_price_cents,
        (array_agg(supplier_id order by price_cents, supplier_id))[1] as best_supplier_id,
        round(avg(price_cents), 2)                      as avg_offer_price_cents,
        sum(available_units)                            as available_units,
        max(observed_on)                                as last_observed_on
    from {{ ref('int_offres__derniere_observation') }}
    group by product_id
)

select
    p.product_id,
    p.sku,
    p.product_name,
    c.category_name,
    coalesce(o.nb_active_offers, 0)                     as nb_active_offers,
    coalesce(o.nb_suppliers, 0)                         as nb_suppliers,
    o.best_price_cents,
    o.best_supplier_id,
    o.avg_offer_price_cents,
    coalesce(o.available_units, 0)                      as available_units,
    o.last_observed_on,
    coalesce(v.quantity_sold, 0)                        as quantity_sold,
    coalesce(v.revenue_cents, 0)                        as revenue_cents,
    v.avg_unit_price_cents,
    v.avg_unit_price_cents - o.best_price_cents         as sale_minus_best_offer_cents,
    case
        when o.product_id is null and v.product_id is null then 'ni_offre_ni_vente'
        when o.product_id is null                          then 'vendu_sans_offre'
        when v.product_id is null                          then 'offre_sans_vente'
        else 'offre_et_ventes'
    end                                                 as coverage_status
from {{ ref('stg_nova__products') }}        as p
join {{ ref('stg_nova__categories') }}      as c on c.category_id = p.category_id
left join offres_par_produit                as o on o.product_id = p.product_id
left join {{ ref('int_ventes__par_produit') }} as v on v.product_id = p.product_id
