-- Le mart couvre tout le catalogue et ses totaux égalent ceux des couches amont.
with mart as (
    select count(*) as lignes, sum(nb_active_offers) as offres,
           sum(quantity_sold) as quantite, sum(revenue_cents) as ca
    from {{ ref('mart_offres_par_produit') }}
), amont as (
    select
        (select count(*) from {{ ref('stg_nova__products') }})                     as produits,
        (select count(distinct offer_id) from {{ ref('stg_fournisseur__offres') }}) as offres,
        (select sum(quantity) from {{ ref('stg_nova__order_lines') }}
          where order_status = 'completed')                                        as quantite,
        (select sum(line_amount_cents) from {{ ref('stg_nova__order_lines') }}
          where order_status = 'completed')                                        as ca
)
select * from mart cross join amont
where mart.lignes <> amont.produits
   or mart.offres <> amont.offres
   or mart.quantite <> amont.quantite
   or mart.ca <> amont.ca
