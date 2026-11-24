-- Règles de domaine rejouées après chargement : montants et unités non négatifs,
-- pas d'observation datée dans le futur.
select offer_id, observed_on, price_cents, available_units
from {{ ref('stg_fournisseur__offres') }}
where price_cents < 0 or available_units < 0 or observed_on > current_date
