-- =====================================================================
-- 04_indicateurs.sql — Indicateurs commerciaux (montants en euros)
-- Règle : on agrège CHAQUE table à son propre grain AVANT de joindre.
-- =====================================================================
\set ON_ERROR_STOP 1

\echo '== Commandes par statut'
SELECT status, count(*) AS commandes
FROM nova.orders
GROUP BY status
ORDER BY commandes DESC;

\echo '== Clients sans commande'
SELECT count(*) AS clients_sans_commande
FROM nova.customers c
WHERE NOT EXISTS (SELECT 1 FROM nova.orders o WHERE o.customer_id = c.customer_id);

\echo '== CA (lignes des commandes terminées) et panier moyen'
-- Périmètre : status = 'completed'. Dénominateur du panier moyen :
-- nombre de commandes terminées (et non nombre de lignes d'articles).
WITH montant_commande AS (
  SELECT o.order_id, sum(i.quantity * i.unit_price_cents) AS montant_cents
  FROM nova.orders o
  JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY o.order_id
)
SELECT count(*)                                    AS commandes_terminees,
       round(sum(montant_cents) / 100.0, 2)        AS ca_euros,
       round(avg(montant_cents) / 100.0, 2)        AS panier_moyen_euros
FROM montant_commande;

\echo '== Rapprochement commandes / paiements, par statut de commande'
-- Articles agrégés par commande, paiements agrégés par commande, PUIS jointure 1-1.
WITH articles AS (
  SELECT order_id, sum(quantity * unit_price_cents) AS montant_articles
  FROM nova.order_items GROUP BY order_id
), paiements AS (
  SELECT order_id,
         count(*)                                                AS nb_paiements,
         sum(amount_cents) FILTER (WHERE status = 'captured')    AS encaisse,
         sum(amount_cents) FILTER (WHERE status = 'pending')     AS en_attente
  FROM nova.payments GROUP BY order_id
)
SELECT o.status,
       count(*)                                                     AS commandes,
       round(sum(a.montant_articles) / 100.0, 2)                    AS articles_euros,
       round(coalesce(sum(p.encaisse), 0) / 100.0, 2)               AS encaisse_euros,
       round(coalesce(sum(p.en_attente), 0) / 100.0, 2)             AS en_attente_euros,
       count(*) FILTER (WHERE a.montant_articles
                        <> coalesce(p.encaisse, 0) + coalesce(p.en_attente, 0)) AS commandes_en_ecart
FROM nova.orders o
JOIN articles a USING (order_id)
LEFT JOIN paiements p USING (order_id)
GROUP BY o.status
ORDER BY o.status;

\echo '== Vérifications de cohérence (attendu : OK partout)'
WITH m AS (
  SELECT o.order_id, o.status, sum(i.quantity * i.unit_price_cents) AS montant
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  GROUP BY o.order_id, o.status
), t AS (
  SELECT (SELECT count(*) FROM nova.orders)                              AS nb_commandes,
         (SELECT count(*) FROM m)                                        AS nb_commandes_agregees,
         (SELECT sum(quantity * unit_price_cents) FROM nova.order_items) AS total_lignes,
         (SELECT sum(montant) FROM m)                                    AS total_par_commande,
         (SELECT sum(montant) FROM m WHERE status = 'completed')         AS ca,
         (SELECT count(*) FROM m WHERE status = 'completed')             AS nb_terminees,
         (SELECT avg(montant) FROM m WHERE status = 'completed')         AS panier,
         (SELECT sum(amount_cents) FROM nova.payments)                   AS total_paiements
)
SELECT 'somme des statuts = nombre de commandes' AS verification,
       CASE WHEN nb_commandes = nb_commandes_agregees THEN 'OK' ELSE 'KO' END AS resultat FROM t
UNION ALL
SELECT 'agrégat par commande = somme des lignes (aucune multiplication)',
       CASE WHEN total_lignes = total_par_commande THEN 'OK' ELSE 'KO' END FROM t
UNION ALL
SELECT 'panier moyen x commandes terminées = CA',
       CASE WHEN round(panier * nb_terminees) = ca THEN 'OK' ELSE 'KO' END FROM t
UNION ALL
SELECT 'total des paiements = total des articles (tous statuts)',
       CASE WHEN total_paiements = total_lignes THEN 'OK' ELSE 'KO' END FROM t;
