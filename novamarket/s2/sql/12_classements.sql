-- =====================================================================
-- 12_classements.sql — S2 / M2 : classements produits et clients
-- Périmètre de vente (identique au CA S1) : commandes status = 'completed',
-- montant = quantity * unit_price_cents (prix de la transaction).
-- Règle de grain : on agrège au grain du classement (produit, client)
-- AVANT d'appliquer la fenêtre.
-- =====================================================================
\set ON_ERROR_STOP 1

\echo '== M2.1 Produits : rang global et rang dans la catégorie (ex æquo visibles)'
-- Grain de sortie : 1 ligne = 1 produit du catalogue.
-- Groupes de comparaison : (a) tout le catalogue, (b) la catégorie feuille,
-- car les catégories regroupent des articles comparables.
-- Ex æquo : RANK (même rang, trou ensuite) est la règle retenue ;
-- DENSE_RANK et ROW_NUMBER sont affichés pour comparaison. ROW_NUMBER
-- départage arbitrairement -> clé de départage explicite product_id.
WITH ventes_produit AS (
  SELECT i.product_id,
         sum(i.quantity * i.unit_price_cents) AS ca_cents,
         sum(i.quantity)                       AS unites
  FROM nova.order_items i
  JOIN nova.orders o USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY i.product_id
)
SELECT p.product_id, p.sku, c.category_name,
       round(coalesce(v.ca_cents, 0) / 100.0, 2) AS ca_euros,
       coalesce(v.unites, 0) AS unites,
       rank()       OVER (ORDER BY coalesce(v.ca_cents, 0) DESC)                         AS rang_global,
       dense_rank() OVER (ORDER BY coalesce(v.ca_cents, 0) DESC)                         AS rang_dense,
       row_number() OVER (ORDER BY coalesce(v.ca_cents, 0) DESC, p.product_id)           AS rang_unique,
       rank()       OVER (PARTITION BY p.category_id ORDER BY coalesce(v.ca_cents, 0) DESC) AS rang_categorie
FROM nova.products p
JOIN nova.categories c USING (category_id)
LEFT JOIN ventes_produit v USING (product_id)     -- garde les produits jamais vendus (CA 0)
ORDER BY rang_global, p.product_id;

\echo '== M2.2 Ex æquo détectés dans le classement produits'
WITH ventes_produit AS (
  SELECT i.product_id, sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.order_items i JOIN nova.orders o USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY i.product_id
)
SELECT round(ca_cents / 100.0, 2) AS ca_euros, count(*) AS produits,
       string_agg(product_id::text, ', ' ORDER BY product_id) AS product_ids
FROM ventes_produit
GROUP BY ca_cents HAVING count(*) > 1
ORDER BY ca_cents DESC;

\echo '== M2.3 Clients : top 10 global et top 3 par ville'
-- Population : clients ayant au moins une commande completed (les clients
-- sans achat n'ont pas de « performance » à classer ; ils sont comptés à part).
-- Grain de sortie : 1 ligne = 1 client.
WITH ca_client AS (
  SELECT o.customer_id,
         count(DISTINCT o.order_id)            AS commandes,
         sum(i.quantity * i.unit_price_cents)  AS ca_cents
  FROM nova.orders o
  JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY o.customer_id
), classe AS (
  SELECT c.customer_id, c.customer_name, c.city, a.commandes, a.ca_cents,
         rank() OVER (ORDER BY a.ca_cents DESC)                    AS rang_global,
         rank() OVER (PARTITION BY c.city ORDER BY a.ca_cents DESC) AS rang_ville,
         count(*) OVER (PARTITION BY c.city)                        AS clients_classes_ville
  FROM ca_client a JOIN nova.customers c USING (customer_id)
)
SELECT customer_id, customer_name, city, commandes,
       round(ca_cents / 100.0, 2) AS ca_euros, rang_global, rang_ville, clients_classes_ville
FROM classe
WHERE rang_global <= 10 OR rang_ville <= 3
ORDER BY city, rang_ville, customer_id;

\echo '== M2.4 Effet d''une duplication sur le classement produits'
-- Même calcul, mais en joignant le catalogue BRUT (reception.products, où
-- product_id 3 apparaît 2 fois) pour récupérer la catégorie. Le CA du
-- produit 3 est doublé et son rang change ; le total est faussé.
WITH ventes AS (
  SELECT i.product_id, i.quantity * i.unit_price_cents AS montant
  FROM nova.order_items i JOIN nova.orders o USING (order_id)
  WHERE o.status = 'completed'
), correct AS (
  SELECT v.product_id, sum(v.montant) AS ca
  FROM ventes v JOIN nova.products p USING (product_id)
  GROUP BY v.product_id
), duplique AS (
  SELECT v.product_id, sum(v.montant) AS ca
  FROM ventes v JOIN reception.products p ON p.product_id::integer = v.product_id
  GROUP BY v.product_id
), rangs AS (
  SELECT c.product_id,
         c.ca AS ca_correct, d.ca AS ca_duplique,
         rank() OVER (ORDER BY c.ca DESC) AS rang_correct,
         rank() OVER (ORDER BY d.ca DESC) AS rang_duplique
  FROM correct c JOIN duplique d USING (product_id)
)
SELECT product_id,
       round(ca_correct / 100.0, 2)  AS ca_correct_euros,
       round(ca_duplique / 100.0, 2) AS ca_duplique_euros,
       rang_correct, rang_duplique,
       rang_correct - rang_duplique  AS places_gagnees
FROM rangs
WHERE ca_correct <> ca_duplique OR rang_correct <> rang_duplique
ORDER BY rang_correct;

\echo '== M2.5 Contrôle : total classé = CA S1'
WITH ventes_produit AS (
  SELECT i.product_id, sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.order_items i JOIN nova.orders o USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY i.product_id
)
SELECT round(sum(ca_cents) / 100.0, 2) AS total_classe_euros,
       CASE WHEN sum(ca_cents) = 2621000 THEN 'OK (= 26 210,00 € S1)' ELSE 'KO' END AS controle
FROM ventes_produit;
