-- =====================================================================
-- 11_controles_catalogue.sql — S2 / M1 : multiplicités, couverture, dates
-- Lecture seule. Pré-requis : 10_catalogue.sql.
-- =====================================================================
\set ON_ERROR_STOP 1

\echo '== M1.1 Multiplicités à la réception (grain attendu : 1 ligne = 1 id)'
SELECT 'categories.csv' AS source, count(*) AS lignes,
       count(DISTINCT category_id) AS ids_distincts,
       count(*) - count(DISTINCT category_id) AS lignes_en_trop
FROM reception.categories
UNION ALL
SELECT 'products.csv', count(*), count(DISTINCT product_id),
       count(*) - count(DISTINCT product_id)
FROM reception.products;

\echo '== M1.2 Identifiants reçus plusieurs fois'
SELECT product_id, count(*) AS occurrences,
       count(DISTINCT (sku, product_name, category_id, first_listed_on)) AS versions_distinctes,
       string_agg(ligne::text, ', ' ORDER BY ligne) AS lignes_source
FROM reception.products
GROUP BY product_id HAVING count(*) > 1;

\echo '== M1.3 Champs vides à la réception'
SELECT 'categories.parent_category_id vide (= racine)' AS controle,
       count(*) FILTER (WHERE nullif(trim(parent_category_id), '') IS NULL) AS lignes
FROM reception.categories
UNION ALL
SELECT 'products : un champ vide',
       count(*) FILTER (WHERE nullif(trim(sku), '') IS NULL OR nullif(trim(product_name), '') IS NULL
                         OR nullif(trim(category_id), '') IS NULL OR nullif(trim(first_listed_on), '') IS NULL)
FROM reception.products;

\echo '== M1.4 Journal des rejets du catalogue'
SELECT source, ligne, cle_source, motif, contenu
FROM rejets.journal
WHERE source IN ('categories.csv', 'products.csv')
ORDER BY source, ligne;

\echo '== M1.5 Couverture ventes <-> catalogue'
SELECT
  (SELECT count(DISTINCT product_id) FROM nova.order_items)                           AS produits_vendus,
  (SELECT count(*) FROM nova.products)                                                AS produits_catalogue,
  (SELECT count(DISTINCT i.product_id) FROM nova.order_items i
    WHERE NOT EXISTS (SELECT 1 FROM nova.products p WHERE p.product_id = i.product_id)) AS vendus_hors_catalogue,
  (SELECT count(*) FROM nova.products p
    WHERE NOT EXISTS (SELECT 1 FROM nova.order_items i WHERE i.product_id = p.product_id)) AS catalogue_jamais_vendu,
  (SELECT count(*) FROM nova.order_items i
    WHERE NOT EXISTS (SELECT 1 FROM nova.products p WHERE p.product_id = i.product_id)) AS lignes_articles_orphelines;

\echo '== M1.6 Lignes d''articles rejetées en S1 : leurs produits sont-ils au catalogue ?'
SELECT j.ligne, j.motif, j.contenu ->> 'product_id' AS product_id,
       EXISTS (SELECT 1 FROM nova.products p WHERE p.product_id = (j.contenu ->> 'product_id')::integer) AS produit_au_catalogue
FROM rejets.journal j
WHERE j.source = 'order_items.csv';

\echo '== M1.7 Catégories : feuilles sans produit, produits par catégorie'
SELECT c.category_id, c.category_name, c.parent_category_id,
       count(p.product_id) AS produits,
       EXISTS (SELECT 1 FROM nova.categories e WHERE e.parent_category_id = c.category_id) AS a_des_enfants
FROM nova.categories c
LEFT JOIN nova.products p USING (category_id)
GROUP BY c.category_id
ORDER BY c.category_id;

\echo '== M1.8 Cohérence des dates : ventes antérieures à la 1re mise en vente déclarée'
SELECT p.product_id, p.sku, p.first_listed_on,
       min(o.ordered_on)                                              AS premiere_vente,
       count(*) FILTER (WHERE o.ordered_on < p.first_listed_on)       AS lignes_avant_mise_en_vente,
       count(*) FILTER (WHERE o.ordered_on < p.first_listed_on
                          AND o.status = 'completed')                 AS dont_completed
FROM nova.products p
JOIN nova.order_items i USING (product_id)
JOIN nova.orders o USING (order_id)
GROUP BY p.product_id
HAVING min(o.ordered_on) < p.first_listed_on
ORDER BY p.product_id;

\echo '== M1.9 Risque de multiplication : jointure des ventes sur le catalogue BRUT (réception)'
-- Démontre pourquoi on ne joint pas la réception : le doublon de product_id 3
-- duplique toutes les lignes d'articles du produit 3.
SELECT 'nova.products (dédoublonné)' AS catalogue_joint,
       count(*) AS lignes_apres_jointure,
       round(sum(i.quantity * i.unit_price_cents) / 100.0, 2) AS montant_euros
FROM nova.order_items i JOIN nova.products p USING (product_id)
UNION ALL
SELECT 'reception.products (brut)', count(*),
       round(sum(i.quantity * i.unit_price_cents) / 100.0, 2)
FROM nova.order_items i JOIN reception.products p ON p.product_id::integer = i.product_id
UNION ALL
SELECT 'référence : nova.order_items seul', count(*),
       round(sum(quantity * unit_price_cents) / 100.0, 2)
FROM nova.order_items;
