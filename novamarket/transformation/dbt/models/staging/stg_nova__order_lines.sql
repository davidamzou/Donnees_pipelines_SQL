-- Grain : une ligne de commande (order_item), enrichie du statut et de la date
-- de sa commande. Jointure n-1 (chaque ligne a exactement une commande) :
-- le nombre de lignes reste celui de nova.order_items.
select
    oi.order_item_id,
    oi.order_id,
    o.ordered_on,
    o.status        as order_status,
    oi.product_id,
    oi.quantity,
    oi.unit_price_cents,
    oi.quantity * oi.unit_price_cents as line_amount_cents
from {{ source('nova', 'order_items') }} as oi
join {{ source('nova', 'orders') }}      as o on o.order_id = oi.order_id
