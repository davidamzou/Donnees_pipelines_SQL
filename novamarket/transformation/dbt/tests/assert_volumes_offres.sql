-- Volumes identiques de la source au modèle intermediate : ni perte (jointures
-- internes) ni multiplication (jointures n-1).
with volumes as (
    select
        (select count(*) from {{ source('fournisseur', 'offres') }})   as source_offres,
        (select count(*) from {{ ref('stg_fournisseur__offres') }})    as staging_offres,
        (select count(*) from {{ ref('int_offres__enrichies') }})      as intermediate_offres
)
select * from volumes
where source_offres <> staging_offres or staging_offres <> intermediate_offres
