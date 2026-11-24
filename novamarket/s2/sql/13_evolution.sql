-- =====================================================================
-- 13_evolution.sql — S2 / M3 : évolution entre périodes (LAG / LEAD)
-- Périmètre : commandes completed, date = ordered_on.
-- =====================================================================
\set ON_ERROR_STOP 1

\echo '== M3.1 Couverture des périodes : jours observés par mois'
-- Un mois est « complet » si ses ventes couvrent du 1er au dernier jour.
SELECT date_trunc('month', ordered_on)::date AS mois,
       min(ordered_on) AS premier_jour, max(ordered_on) AS dernier_jour,
       count(DISTINCT ordered_on) AS jours_avec_commande,
       extract(day FROM date_trunc('month', ordered_on) + interval '1 month - 1 day')::int AS jours_du_mois
FROM nova.orders
GROUP BY date_trunc('month', ordered_on) ORDER BY 1;

\echo '== M3.2 CA mensuel, LAG / LEAD, sur un calendrier complet (mois manquants = 0)'
-- generate_series fabrique le calendrier : un mois sans vente apparaîtrait
-- avec 0 au lieu d'être sauté (sinon LAG comparerait mars à janvier).
WITH bornes AS (
  SELECT date_trunc('month', min(ordered_on))::date AS debut,
         date_trunc('month', max(ordered_on))::date AS fin,
         max(ordered_on) AS derniere_date
  FROM nova.orders
), calendrier AS (
  SELECT gs::date AS mois FROM bornes, generate_series(debut, fin, interval '1 month') gs
), ca_mois AS (
  SELECT date_trunc('month', o.ordered_on)::date AS mois,
         count(DISTINCT o.order_id) AS commandes,
         sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY 1
), serie AS (
  SELECT k.mois, coalesce(m.commandes, 0) AS commandes, coalesce(m.ca_cents, 0) AS ca_cents,
         CASE WHEN k.mois + interval '1 month - 1 day' > b.derniere_date
              THEN 'INCOMPLET (jusqu''au ' || to_char(b.derniere_date, 'DD/MM') || ')'
              ELSE 'complet' END AS couverture
  FROM calendrier k CROSS JOIN bornes b LEFT JOIN ca_mois m USING (mois)
)
SELECT mois, couverture, commandes,
       round(ca_cents / 100.0, 2)                                    AS ca_euros,
       round(lag(ca_cents)  OVER w / 100.0, 2)                       AS ca_mois_precedent,
       round(lead(ca_cents) OVER w / 100.0, 2)                       AS ca_mois_suivant,
       round(100.0 * (ca_cents - lag(ca_cents) OVER w)
             / nullif(lag(ca_cents) OVER w, 0), 1)                   AS evolution_pct
FROM serie
WINDOW w AS (ORDER BY mois)
ORDER BY mois;

\echo '== M3.3 Comparaison à périmètre égal : jours 1 à 19 de chaque mois'
-- Novembre s'arrête le 19 : on compare chaque mois sur ses 19 premiers jours
-- pour neutraliser l'effet « période incomplète ».
WITH ca AS (
  SELECT date_trunc('month', o.ordered_on)::date AS mois,
         sum(i.quantity * i.unit_price_cents) AS ca_cents,
         count(DISTINCT o.order_id) AS commandes
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
    AND extract(day FROM o.ordered_on) <= (SELECT extract(day FROM max(ordered_on)) FROM nova.orders)
  GROUP BY 1
)
SELECT mois, commandes, round(ca_cents / 100.0, 2) AS ca_j1_j19_euros,
       round(lag(ca_cents) OVER (ORDER BY mois) / 100.0, 2) AS precedent,
       round(100.0 * (ca_cents - lag(ca_cents) OVER (ORDER BY mois))
             / nullif(lag(ca_cents) OVER (ORDER BY mois), 0), 1) AS evolution_pct
FROM ca ORDER BY mois;

\echo '== M3.4 CA hebdomadaire (semaines ISO) avec LAG et repérage des semaines partielles'
WITH bornes AS (SELECT min(ordered_on) AS d0, max(ordered_on) AS d1 FROM nova.orders),
semaines AS (
  SELECT gs::date AS semaine
  FROM bornes, generate_series(date_trunc('week', d0), date_trunc('week', d1), interval '1 week') gs
), ca AS (
  SELECT date_trunc('week', o.ordered_on)::date AS semaine,
         sum(i.quantity * i.unit_price_cents) AS ca_cents,
         count(DISTINCT o.ordered_on) AS jours_observes
  FROM nova.orders o JOIN nova.order_items i USING (order_id)
  WHERE o.status = 'completed'
  GROUP BY 1
)
SELECT s.semaine, coalesce(c.jours_observes, 0) AS jours_observes,
       CASE WHEN s.semaine < (SELECT d0 FROM bornes) OR s.semaine + 6 > (SELECT d1 FROM bornes)
            THEN 'partielle' ELSE 'pleine' END AS couverture,
       round(coalesce(c.ca_cents, 0) / 100.0, 2) AS ca_euros,
       round(lag(coalesce(c.ca_cents, 0)) OVER (ORDER BY s.semaine) / 100.0, 2) AS semaine_precedente,
       round(coalesce(c.ca_cents, 0) / 100.0 - lag(coalesce(c.ca_cents, 0)) OVER (ORDER BY s.semaine) / 100.0, 2) AS ecart_euros
FROM semaines s LEFT JOIN ca c USING (semaine)
ORDER BY s.semaine;

\echo '== M3.5 Évolution mensuelle par catégorie feuille (LAG partitionné)'
WITH ca AS (
  SELECT p.category_id, date_trunc('month', o.ordered_on)::date AS mois,
         sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.orders o
  JOIN nova.order_items i USING (order_id)
  JOIN nova.products p USING (product_id)
  WHERE o.status = 'completed'
  GROUP BY 1, 2
)
SELECT c.category_name, ca.mois, round(ca.ca_cents / 100.0, 2) AS ca_euros,
       round(lag(ca.ca_cents) OVER w / 100.0, 2) AS precedent,
       round(100.0 * (ca.ca_cents - lag(ca.ca_cents) OVER w) / nullif(lag(ca.ca_cents) OVER w, 0), 1) AS evolution_pct
FROM ca JOIN nova.categories c USING (category_id)
WINDOW w AS (PARTITION BY ca.category_id ORDER BY ca.mois)
ORDER BY c.category_name, ca.mois;

\echo '== M3.6 Cohérence ventes / catalogue : ventes avant first_listed_on, par mois'
-- Incohérence DÉMONTRÉE (≠ évolution inhabituelle) : une vente ne peut pas
-- précéder la première mise en vente. Ce n'est pas une variation de CA.
SELECT p.product_id, p.first_listed_on, date_trunc('month', o.ordered_on)::date AS mois,
       count(*) AS lignes, count(*) FILTER (WHERE o.ordered_on < p.first_listed_on) AS lignes_avant_mise_en_vente,
       round(sum(i.quantity * i.unit_price_cents) FILTER (WHERE o.ordered_on < p.first_listed_on
                                                           AND o.status = 'completed') / 100.0, 2) AS ca_completed_concerne_euros
FROM nova.products p
JOIN nova.order_items i USING (product_id)
JOIN nova.orders o USING (order_id)
WHERE p.product_id IN (SELECT p2.product_id FROM nova.products p2
                       JOIN nova.order_items i2 USING (product_id)
                       JOIN nova.orders o2 USING (order_id)
                       WHERE o2.ordered_on < p2.first_listed_on)
GROUP BY 1, 2, 3 ORDER BY 1, 3;
