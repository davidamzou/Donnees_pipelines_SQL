-- =====================================================================
-- 15_hierarchie.sql — S2 / M5 (A1) : hiérarchie des catégories
-- WITH RECURSIVE, contrôle des cycles, CA consolidé par branche.
-- =====================================================================
\set ON_ERROR_STOP 1

\echo '== M5.1 Arbre des catégories (chemin, profondeur, cycle)'
-- Ancre : catégories racines (parent NULL). Récursion : enfants.
-- La clause CYCLE (PostgreSQL >= 14) marque et stoppe un éventuel cycle ;
-- la profondeur < 20 est un garde-fou supplémentaire.
WITH RECURSIVE arbre AS (
  SELECT category_id, category_name, parent_category_id,
         category_id AS racine_id, 0 AS profondeur,
         category_name::text AS chemin
  FROM nova.categories
  WHERE parent_category_id IS NULL
  UNION ALL
  SELECT c.category_id, c.category_name, c.parent_category_id,
         a.racine_id, a.profondeur + 1,
         a.chemin || ' > ' || c.category_name
  FROM nova.categories c
  JOIN arbre a ON c.parent_category_id = a.category_id
  WHERE a.profondeur < 20
) CYCLE category_id SET est_cycle USING parcours
SELECT category_id, profondeur, chemin, est_cycle,
       (SELECT count(*) FROM nova.products p WHERE p.category_id = arbre.category_id) AS produits_directs
FROM arbre
ORDER BY chemin;

\echo '== M5.2 Contrôles de rattachement'
-- (a) catégories non atteintes depuis une racine (orphelines ou prises dans
--     un cycle sans racine), (b) catégories atteintes plusieurs fois,
-- (c) produits rattachés à une catégorie NON feuille.
WITH RECURSIVE arbre AS (
  SELECT category_id, 0 AS profondeur FROM nova.categories WHERE parent_category_id IS NULL
  UNION ALL
  SELECT c.category_id, a.profondeur + 1
  FROM nova.categories c JOIN arbre a ON c.parent_category_id = a.category_id
  WHERE a.profondeur < 20
)
SELECT 'catégories du référentiel' AS controle, count(*)::bigint AS valeur FROM nova.categories
UNION ALL SELECT 'catégories atteintes depuis une racine', count(DISTINCT category_id) FROM arbre
UNION ALL SELECT 'catégories non atteintes (orpheline / cycle)',
         count(*) FROM nova.categories c WHERE NOT EXISTS (SELECT 1 FROM arbre a WHERE a.category_id = c.category_id)
UNION ALL SELECT 'catégories atteintes plusieurs fois', count(*) FROM (SELECT category_id FROM arbre GROUP BY 1 HAVING count(*) > 1) d
UNION ALL SELECT 'profondeur maximale', max(profondeur) FROM arbre
UNION ALL SELECT 'produits rattachés à une catégorie non feuille',
         count(*) FROM nova.products p
         WHERE EXISTS (SELECT 1 FROM nova.categories e WHERE e.parent_category_id = p.category_id);

\echo '== M5.3 CA consolidé par branche (chaque catégorie + tous ses descendants)'
-- Table de fermeture (ancêtre, descendant) : chaque catégorie est sa propre
-- descendante (profondeur 0). Le CA d'un produit remonte vers TOUS ses
-- ancêtres : il est donc compté une fois par niveau. On ne peut additionner
-- que des branches disjointes (ex. les racines), jamais toutes les lignes.
WITH RECURSIVE fermeture AS (
  SELECT category_id AS ancetre_id, category_id AS descendant_id, 0 AS distance
  FROM nova.categories
  UNION ALL
  SELECT f.ancetre_id, c.category_id, f.distance + 1
  FROM fermeture f JOIN nova.categories c ON c.parent_category_id = f.descendant_id
  WHERE f.distance < 20
), ca_categorie AS (            -- grain : 1 ligne = 1 catégorie feuille
  SELECT p.category_id, sum(i.quantity * i.unit_price_cents) AS ca_cents,
         count(DISTINCT p.product_id) AS produits_vendus
  FROM nova.order_items i
  JOIN nova.orders o USING (order_id)
  JOIN nova.products p USING (product_id)
  WHERE o.status = 'completed'
  GROUP BY p.category_id
)
SELECT a.category_id, a.category_name, a.parent_category_id,
       count(DISTINCT f.descendant_id) - 1                 AS sous_categories,
       coalesce(sum(cc.produits_vendus), 0)                AS produits_vendus,
       round(coalesce(sum(cc.ca_cents), 0) / 100.0, 2)     AS ca_branche_euros,
       round(100.0 * coalesce(sum(cc.ca_cents), 0) / 2621000, 1) AS part_ca_total_pct
FROM nova.categories a
JOIN fermeture f ON f.ancetre_id = a.category_id
LEFT JOIN ca_categorie cc ON cc.category_id = f.descendant_id
GROUP BY a.category_id
ORDER BY a.parent_category_id NULLS FIRST, ca_branche_euros DESC;

\echo '== M5.4 Contrôle anti double comptage'
WITH RECURSIVE fermeture AS (
  SELECT category_id AS ancetre_id, category_id AS descendant_id FROM nova.categories
  UNION ALL
  SELECT f.ancetre_id, c.category_id
  FROM fermeture f JOIN nova.categories c ON c.parent_category_id = f.descendant_id
), ca_categorie AS (
  SELECT p.category_id, sum(i.quantity * i.unit_price_cents) AS ca_cents
  FROM nova.order_items i JOIN nova.orders o USING (order_id) JOIN nova.products p USING (product_id)
  WHERE o.status = 'completed'
  GROUP BY p.category_id
), par_branche AS (
  SELECT a.category_id, a.parent_category_id, coalesce(sum(cc.ca_cents), 0) AS ca_cents
  FROM nova.categories a
  JOIN fermeture f ON f.ancetre_id = a.category_id
  LEFT JOIN ca_categorie cc ON cc.category_id = f.descendant_id
  GROUP BY a.category_id
)
SELECT round(sum(ca_cents) FILTER (WHERE parent_category_id IS NULL) / 100.0, 2) AS somme_racines_euros,
       round(sum(ca_cents) / 100.0, 2)                                           AS somme_toutes_branches_euros,
       26210.00                                                                  AS ca_s1_euros,
       CASE WHEN sum(ca_cents) FILTER (WHERE parent_category_id IS NULL) = 2621000
            THEN 'OK : racines = CA' ELSE 'KO' END                               AS controle
FROM par_branche;
