-- Ancrage métier : le CA du périmètre S2 (commandes completed) vaut 26 210,00 €
-- (SOLUTION_S2.md). Un écart signale une jointure ou un filtre erroné.
select sum(revenue_cents) as ca_cents
from {{ ref('mart_offres_par_produit') }}
having sum(revenue_cents) <> 2621000
