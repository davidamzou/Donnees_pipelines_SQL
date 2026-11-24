-- Grain : un fournisseur.
select
    supplier_id,
    supplier_name
from {{ source('fournisseur', 'fournisseurs') }}
