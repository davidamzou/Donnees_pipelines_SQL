-- =====================================================================
-- 14_segmentation.sql — S2 / M4 (A1) : segmentation NTILE(4) des clients
-- Population : clients ayant >= 1 commande completed (120 sur 180).
--   Les 60 autres (30 sans commande, 30 avec seulement pending/cancelled)
--   forment un segment « sans achat » à part : les inclure avec CA = 0
--   remplirait le dernier quartile d'ex æquo à 0 et la frontière serait
--   arbitraire.
-- Mesure : CA completed en centimes (quantity * unit_price_cents).
-- Ordre : CA décroissant, départage par customer_id pour un résultat
--   déterministe (sinon deux clients ex æquo à une frontière peuvent changer
--   de quartile d'une exécution à l'autre).
-- =====================================================================
\set ON_ERROR_STOP 1

\echo '== M4.1 Bilan des quartiles'
WITH ca_client AS (
  SELECT o.customer_id, sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY o.customer_id
), seg AS (
  SELECT customer_id, ca_cents,
         ntile(4) OVER (ORDER BY ca_cents DESC, customer_id) AS quartile
  FROM ca_client
)
SELECT quartile, count(*) AS clients,
       round(min(ca_cents) / 100.0, 2) AS ca_min, round(max(ca_cents) / 100.0, 2) AS ca_max,
       round(avg(ca_cents) / 100.0, 2) AS ca_moyen,
       round(sum(ca_cents) / 100.0, 2) AS ca_total,
       round(100.0 * sum(ca_cents) / sum(sum(ca_cents)) OVER (), 1) AS part_ca_pct
FROM seg GROUP BY quartile
UNION ALL
SELECT NULL, (SELECT count(*) FROM nova.customers) - (SELECT count(*) FROM ca_client),
       0, 0, 0, 0, 0
ORDER BY quartile NULLS LAST;

\echo '== M4.2 Ex æquo coupés par une frontière de quartile'
-- Un même CA présent dans deux quartiles : la frontière tombe au milieu
-- d'un groupe d'égalités ; seul customer_id décide.
WITH ca_client AS (
  SELECT o.customer_id, sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY o.customer_id
), seg AS (
  SELECT customer_id, ca_cents, ntile(4) OVER (ORDER BY ca_cents DESC, customer_id) AS quartile
  FROM ca_client
)
SELECT round(ca_cents / 100.0, 2) AS ca_euros,
       string_agg(DISTINCT quartile::text, ' / ') AS quartiles,
       count(*) AS clients,
       string_agg(customer_id || '→Q' || quartile, ', ' ORDER BY customer_id) AS affectation
FROM seg
GROUP BY ca_cents HAVING count(DISTINCT quartile) > 1
ORDER BY ca_cents DESC;

\echo '== M4.3 Alternative sans coupure d''ex æquo : quartile par rang (RANK)'
-- Les égalités restent ensemble ; les effectifs ne sont plus forcément égaux.
WITH ca_client AS (
  SELECT o.customer_id, sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY o.customer_id
), r AS (
  SELECT customer_id, ca_cents, rank() OVER (ORDER BY ca_cents DESC) AS rang,
         count(*) OVER () AS n
  FROM ca_client
)
SELECT 1 + ((rang - 1) * 4) / n AS quartile_par_rang, count(*) AS clients,
       round(min(ca_cents) / 100.0, 2) AS ca_min, round(max(ca_cents) / 100.0, 2) AS ca_max
FROM r GROUP BY 1 ORDER BY 1;
