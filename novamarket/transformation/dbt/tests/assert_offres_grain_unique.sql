-- Grain du staging : au plus une ligne par (offer_id, observed_on).
select offer_id, observed_on, count(*) as nb
from {{ ref('stg_fournisseur__offres') }}
group by offer_id, observed_on
having count(*) > 1
