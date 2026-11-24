-- Grain conservé : une offre observée un jour donné (offer_id, observed_on).
-- Harmonisation : noms explicites, montant en euros dérivé, sans filtre ni jointure.
select
    offer_id,
    observed_on,
    supplier_id,
    product_id,
    price_cents,
    round(price_cents / 100.0, 2)  as price_eur,
    currency,
    available_units,
    lot_insertion                  as loaded_in_lot_id,
    lot_maj                        as updated_in_lot_id
from {{ source('fournisseur', 'offres') }}
