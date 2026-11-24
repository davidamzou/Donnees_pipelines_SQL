-- S4 · M5 : volumes de la source au mart, absence de multiplication, contenu du mart.
\pset footer off

\echo '--- Volumes par couche (grain entre parenthèses)'
SELECT 'source fournisseur.offres (offre x jour)'                AS relation, count(*) AS lignes FROM fournisseur.offres
UNION ALL SELECT 'staging stg_fournisseur__offres (offre x jour)',            count(*) FROM dbt_dev_staging.stg_fournisseur__offres
UNION ALL SELECT 'intermediate int_offres__enrichies (offre x jour)',         count(*) FROM dbt_dev_intermediate.int_offres__enrichies
UNION ALL SELECT 'offres distinctes (offre)',                                 count(DISTINCT offer_id) FROM dbt_dev_staging.stg_fournisseur__offres
UNION ALL SELECT 'catalogue nova.products (produit)',                         count(*) FROM nova.products
UNION ALL SELECT 'mart mart_offres_par_produit (produit)',                    count(*) FROM dbt_dev_marts.mart_offres_par_produit;

\echo '--- Totaux du mart = totaux amont (pas de multiplication par les jointures)'
SELECT
    (SELECT sum(nb_active_offers) FROM dbt_dev_marts.mart_offres_par_produit)  AS offres_mart,
    (SELECT count(DISTINCT offer_id) FROM fournisseur.offres)                  AS offres_source,
    (SELECT sum(revenue_cents) FROM dbt_dev_marts.mart_offres_par_produit)     AS ca_mart_cents,
    (SELECT sum(oi.quantity * oi.unit_price_cents)
       FROM nova.order_items oi JOIN nova.orders o USING (order_id)
      WHERE o.status = 'completed')                                            AS ca_s2_cents;

\echo '--- Couverture du catalogue'
SELECT coverage_status, count(*) AS produits, sum(nb_active_offers) AS offres
FROM dbt_dev_marts.mart_offres_par_produit GROUP BY 1 ORDER BY 1;

\echo '--- Mart complet'
SELECT product_id, product_name, category_name, nb_active_offers AS offres, best_supplier_id AS fournisseur,
       best_price_cents AS prix_min, available_units AS stock, quantity_sold AS qte_vendue,
       avg_unit_price_cents AS prix_vente_moy, sale_minus_best_offer_cents AS ecart, coverage_status
FROM dbt_dev_marts.mart_offres_par_produit ORDER BY product_id;

\echo '--- Matérialisations créées par dbt (l éphémère n apparaît pas)'
SELECT table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_schema LIKE 'dbt_dev%'
ORDER BY 1, 2;
