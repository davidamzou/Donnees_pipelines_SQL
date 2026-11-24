{{ config(materialized='ephemeral') }}
-- Dernier état connu de chaque offre.
-- Grain : une ligne par offer_id (la plus récente observation).
-- Éphémère : ce SQL est injecté comme CTE dans le modèle aval, aucune relation
-- n'est créée dans PostgreSQL.
select *
from (
    select
        e.*,
        row_number() over (partition by e.offer_id order by e.observed_on desc) as rang_recent
    from {{ ref('int_offres__enrichies') }} as e
) as classees
where rang_recent = 1
