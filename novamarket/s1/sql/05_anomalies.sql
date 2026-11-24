-- =====================================================================
-- 05_anomalies.sql — Démonstrations demandées par SOURCES.md
-- Lit la RÉCEPTION (données brutes) pour montrer les anomalies, et le
-- schéma nova pour montrer les pièges de jointure.
-- =====================================================================
\set ON_ERROR_STOP 1

-- ---------------------------------------------------------------------
-- 1. Doublons réels
-- ---------------------------------------------------------------------
\echo '== 1a. Identifiants reçus plusieurs fois (toutes sources)'
SELECT 'order_items.csv' AS source, order_item_id AS id, count(*) AS occurrences,
       count(DISTINCT (order_id, product_id, quantity, unit_price_cents)) AS contenus_distincts
FROM reception.order_items GROUP BY order_item_id HAVING count(*) > 1
UNION ALL
SELECT 'orders.csv', order_id, count(*), count(DISTINCT (customer_id, ordered_on, status))
FROM reception.orders GROUP BY order_id HAVING count(*) > 1
UNION ALL
SELECT 'customers.csv', customer_id, count(*), count(DISTINCT (customer_name, city))
FROM reception.customers GROUP BY customer_id HAVING count(*) > 1
UNION ALL
SELECT 'payments.ndjson', document::jsonb ->> 'payment_id', count(*), count(DISTINCT document)
FROM reception.payments GROUP BY 2 HAVING count(*) > 1;

\echo '== 1b. Faux doublons : paiements de même commande/date/montant mais payment_id distincts'
-- Ils sont légitimes : leur somme égale le montant des articles (paiement fractionné).
WITH p AS (
  SELECT order_id, paid_on, amount_cents, status, count(*) AS nb
  FROM nova.payments GROUP BY order_id, paid_on, amount_cents, status HAVING count(*) > 1
), a AS (
  SELECT order_id, sum(quantity * unit_price_cents) AS montant_articles FROM nova.order_items GROUP BY order_id
)
SELECT count(*) AS paires_identiques,
       count(*) FILTER (WHERE p.amount_cents * p.nb = a.montant_articles) AS dont_somme_egale_commande
FROM p JOIN a USING (order_id);

-- ---------------------------------------------------------------------
-- 2. Références orphelines
-- ---------------------------------------------------------------------
\echo '== 2. Lignes d''articles / paiements reçus dont la commande n''existe pas'
SELECT 'order_items.csv' AS source, i.ligne, i.order_item_id AS id, i.order_id
FROM reception.order_items i
WHERE NOT EXISTS (SELECT 1 FROM reception.orders o WHERE o.order_id = i.order_id)
UNION ALL
SELECT 'payments.ndjson', p.ligne, p.document::jsonb ->> 'payment_id', p.document::jsonb ->> 'order_id'
FROM reception.payments p
WHERE NOT EXISTS (SELECT 1 FROM reception.orders o WHERE o.order_id = p.document::jsonb ->> 'order_id')
UNION ALL
SELECT 'orders.csv', o.ligne, o.order_id, o.customer_id
FROM reception.orders o
WHERE NOT EXISTS (SELECT 1 FROM reception.customers c WHERE c.customer_id = o.customer_id);

\echo '== 2b. Effet du doublon + de l''orphelin si on avait chargé le brut sans contrôle'
SELECT round(sum(quantity::int * unit_price_cents::int) / 100.0, 2) AS montant_brut_toutes_lignes_euros,
       (SELECT round(sum(quantity * unit_price_cents) / 100.0, 2) FROM nova.order_items) AS montant_integre_euros
FROM reception.order_items;

-- ---------------------------------------------------------------------
-- 3. Multiplication des lignes lors des jointures (grains différents)
-- ---------------------------------------------------------------------
\echo '== 3. Piège : joindre articles ET paiements avant d''agréger'
-- Une commande à N articles et M paiements produit N x M lignes :
-- chaque article est compté M fois, chaque paiement N fois.
WITH faux AS (
  SELECT sum(i.quantity * i.unit_price_cents) AS articles_faux,
         sum(p.amount_cents)                  AS paiements_faux,
         count(*)                             AS lignes_jointure
  FROM nova.orders o
  JOIN nova.order_items i USING (order_id)
  JOIN nova.payments    p USING (order_id)
), juste AS (
  SELECT (SELECT sum(quantity * unit_price_cents) FROM nova.order_items) AS articles_juste,
         (SELECT sum(amount_cents) FROM nova.payments)                   AS paiements_juste,
         (SELECT count(*) FROM nova.order_items)                         AS lignes_articles
)
SELECT lignes_articles, lignes_jointure,
       round(articles_juste / 100.0, 2)  AS articles_juste_euros,
       round(articles_faux  / 100.0, 2)  AS articles_faux_euros,
       round(paiements_juste / 100.0, 2) AS paiements_juste_euros,
       round(paiements_faux  / 100.0, 2) AS paiements_faux_euros
FROM faux, juste;

\echo '== 3b. Exemple concret : une commande à 2 articles et 2 paiements'
WITH cible AS (
  SELECT order_id FROM nova.payments GROUP BY order_id HAVING count(*) = 2
  INTERSECT
  SELECT order_id FROM nova.order_items GROUP BY order_id HAVING count(*) = 2
  ORDER BY order_id LIMIT 1
)
SELECT o.order_id, i.order_item_id, i.quantity * i.unit_price_cents AS montant_ligne,
       p.payment_id, p.amount_cents
FROM cible JOIN nova.orders o USING (order_id)
JOIN nova.order_items i USING (order_id)
JOIN nova.payments    p USING (order_id)
ORDER BY i.order_item_id, p.payment_id;

-- ---------------------------------------------------------------------
-- 4. Impact du statut de commande sur le périmètre du CA
-- ---------------------------------------------------------------------
\echo '== 4. CA selon le périmètre de statuts retenu'
WITH m AS (
  SELECT o.status, sum(i.quantity * i.unit_price_cents) AS montant
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  GROUP BY o.status
)
SELECT 'completed seul (retenu)'           AS perimetre, round(sum(montant) FILTER (WHERE status = 'completed') / 100.0, 2) AS ca_euros FROM m
UNION ALL
SELECT 'completed + pending',               round(sum(montant) FILTER (WHERE status IN ('completed', 'pending')) / 100.0, 2) FROM m
UNION ALL
SELECT 'tous statuts (faux : inclut annulées)', round(sum(montant) / 100.0, 2) FROM m;

\echo '== 4b. Commandes annulées mais avec paiements encaissés (remboursement non tracé ?)'
SELECT count(DISTINCT o.order_id)            AS commandes_annulees_encaissees,
       round(sum(p.amount_cents) / 100.0, 2) AS montant_encaisse_euros
FROM nova.orders o JOIN nova.payments p USING (order_id)
WHERE o.status = 'cancelled' AND p.status = 'captured';
