-- Ventes réalisées par produit, périmètre S2 : commandes au statut 'completed',
-- montant = quantité x prix de la transaction.
-- Grain : un produit vendu au moins une fois.
select
    product_id,
    sum(quantity)                                   as quantity_sold,
    sum(line_amount_cents)                          as revenue_cents,
    round(sum(line_amount_cents)::numeric / sum(quantity), 2) as avg_unit_price_cents
from {{ ref('stg_nova__order_lines') }}
where order_status = 'completed'
group by product_id
