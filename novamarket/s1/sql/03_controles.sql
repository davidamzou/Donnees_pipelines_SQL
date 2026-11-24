-- =====================================================================
-- 03_controles.sql — Volumes reçus / intégrés / rejetés et causes
-- Contrôle clé : reçus = intégrés + rejetés pour chaque source.
-- =====================================================================
\set ON_ERROR_STOP 1

\echo '== Bilan des volumes par source'
WITH recu AS (
  SELECT 'customers.csv' AS source, count(*) AS recus FROM reception.customers
  UNION ALL SELECT 'orders.csv',      count(*) FROM reception.orders
  UNION ALL SELECT 'order_items.csv', count(*) FROM reception.order_items
  UNION ALL SELECT 'payments.ndjson', count(*) FROM reception.payments
), integre AS (
  SELECT 'customers.csv' AS source, count(*) AS integres FROM nova.customers
  UNION ALL SELECT 'orders.csv',      count(*) FROM nova.orders
  UNION ALL SELECT 'order_items.csv', count(*) FROM nova.order_items
  UNION ALL SELECT 'payments.ndjson', count(*) FROM nova.payments
), rejete AS (
  SELECT source, count(*) AS rejetes FROM rejets.journal GROUP BY source
)
SELECT r.source, r.recus, i.integres, coalesce(j.rejetes, 0) AS rejetes,
       CASE WHEN r.recus = i.integres + coalesce(j.rejetes, 0) THEN 'OK' ELSE 'ÉCART !' END AS bilan
FROM recu r
JOIN integre i USING (source)
LEFT JOIN rejete j USING (source)
ORDER BY r.source;

\echo '== Journal des rejets'
SELECT source, ligne, cle_source, motif, contenu
FROM rejets.journal
ORDER BY source, ligne;

\echo '== Contrôles d''intégrité après intégration (tous doivent valoir 0)'
SELECT 'lignes de commande sans commande' AS controle, count(*) AS nb
FROM nova.order_items i LEFT JOIN nova.orders o USING (order_id) WHERE o.order_id IS NULL
UNION ALL
SELECT 'paiements sans commande', count(*)
FROM nova.payments p LEFT JOIN nova.orders o USING (order_id) WHERE o.order_id IS NULL
UNION ALL
SELECT 'commandes sans ligne d''article', count(*)
FROM nova.orders o WHERE NOT EXISTS (SELECT 1 FROM nova.order_items i WHERE i.order_id = o.order_id);
