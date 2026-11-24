-- =====================================================================
-- 10_catalogue.sql — S2 / M1 : intégration du catalogue dans la base S1
-- Pré-requis : base S1 chargée (s1/sql/run_all.sh) et fichiers copiés dans
-- le conteneur sous /tmp/novamarket-s2 (voir s2/sql/run_s2.sh).
-- Rejouable : supprime puis recrée UNIQUEMENT les objets catalogue.
-- Les tables S1 (nova.customers/orders/order_items/payments) ne sont pas
-- modifiées, à l'exception d'une clé étrangère ajoutée sur order_items.
-- Même règle qu'en S1 : chaque ligne reçue va SOIT dans nova.*, SOIT dans
-- rejets.journal (1re occurrence conservée, suivantes rejetées).
-- =====================================================================
\set ON_ERROR_STOP 1
BEGIN;

-- ---------------------------------------------------------------------
-- 0. Nettoyage (rejouabilité)
-- ---------------------------------------------------------------------
ALTER TABLE nova.order_items DROP CONSTRAINT IF EXISTS order_items_product_fk;
DROP TABLE IF EXISTS nova.products;
DROP TABLE IF EXISTS nova.categories;
DROP TABLE IF EXISTS reception.products;
DROP TABLE IF EXISTS reception.categories;
DELETE FROM rejets.journal WHERE source IN ('categories.csv', 'products.csv');

-- ---------------------------------------------------------------------
-- 1. RÉCEPTION brute (text, n° de ligne)
-- ---------------------------------------------------------------------
CREATE TABLE reception.categories (
    ligne              bigint GENERATED ALWAYS AS IDENTITY,
    category_id        text,
    category_name      text,
    parent_category_id text
);
CREATE TABLE reception.products (
    ligne           bigint GENERATED ALWAYS AS IDENTITY,
    product_id      text,
    sku             text,
    product_name    text,
    category_id     text,
    first_listed_on text
);

\copy reception.categories (category_id, category_name, parent_category_id) FROM '/tmp/novamarket-s2/categories.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy reception.products (product_id, sku, product_name, category_id, first_listed_on) FROM '/tmp/novamarket-s2/products.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

-- ---------------------------------------------------------------------
-- 2. MÉTIER : tables typées et contraintes
-- ---------------------------------------------------------------------
CREATE TABLE nova.categories (
    category_id        integer PRIMARY KEY,
    category_name      text    NOT NULL,
    parent_category_id integer REFERENCES nova.categories (category_id),
    CHECK (parent_category_id IS DISTINCT FROM category_id)   -- pas d'auto-boucle
);
CREATE INDEX ON nova.categories (parent_category_id);

CREATE TABLE nova.products (
    product_id      integer PRIMARY KEY,
    sku             text    NOT NULL UNIQUE,
    product_name    text    NOT NULL,
    category_id     integer NOT NULL REFERENCES nova.categories (category_id),
    first_listed_on date    NOT NULL
);
CREATE INDEX ON nova.products (category_id);

-- ---------------------------------------------------------------------
-- 3. CATEGORIES : contrôles puis intégration
--    Le parent doit exister DANS LE FICHIER (et être valide) ; l'ordre des
--    lignes n'importe pas car l'insertion se fait en une seule instruction
--    (FK vérifiée en fin d'instruction).
-- ---------------------------------------------------------------------
CREATE TEMP TABLE chk_categories AS
SELECT r.*,
  CASE
    WHEN NOT pg_input_is_valid(r.category_id, 'integer')          THEN 'category_id non entier'
    WHEN nullif(trim(r.category_name), '') IS NULL                 THEN 'category_name manquant'
    WHEN nullif(trim(r.parent_category_id), '') IS NOT NULL
     AND NOT pg_input_is_valid(r.parent_category_id, 'integer')    THEN 'parent_category_id non entier'
    WHEN r.rang > 1 AND r.contenu = r.contenu_1er                  THEN 'doublon exact de category_id'
    WHEN r.rang > 1                                                THEN 'conflit : category_id déjà reçu avec un autre contenu'
    WHEN nullif(trim(r.parent_category_id), '') IS NOT NULL
     AND trim(r.parent_category_id) = trim(r.category_id)          THEN 'catégorie parente d''elle-même'
    WHEN nullif(trim(r.parent_category_id), '') IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM reception.categories p
                     WHERE trim(p.category_id) = trim(r.parent_category_id))
                                                                   THEN 'catégorie parente inconnue (orpheline)'
  END AS motif
FROM (
  SELECT c.*,
         row_number() OVER w AS rang,
         (c.category_name, c.parent_category_id)::text AS contenu,
         first_value((c.category_name, c.parent_category_id)::text) OVER w AS contenu_1er
  FROM reception.categories c
  WINDOW w AS (PARTITION BY trim(c.category_id) ORDER BY c.ligne)
) r;

INSERT INTO rejets.journal (source, ligne, cle_source, motif, contenu)
SELECT 'categories.csv', ligne, category_id, motif,
       jsonb_build_object('category_id', category_id, 'category_name', category_name,
                          'parent_category_id', parent_category_id)
FROM chk_categories WHERE motif IS NOT NULL;

INSERT INTO nova.categories (category_id, category_name, parent_category_id)
SELECT trim(category_id)::integer, trim(category_name),
       nullif(trim(parent_category_id), '')::integer
FROM chk_categories WHERE motif IS NULL;

-- ---------------------------------------------------------------------
-- 4. PRODUCTS : contrôles puis intégration
-- ---------------------------------------------------------------------
CREATE TEMP TABLE chk_products AS
SELECT r.*,
  CASE
    WHEN NOT pg_input_is_valid(r.product_id, 'integer')        THEN 'product_id non entier'
    WHEN nullif(trim(r.sku), '') IS NULL                        THEN 'sku manquant'
    WHEN nullif(trim(r.product_name), '') IS NULL               THEN 'product_name manquant'
    WHEN NOT pg_input_is_valid(r.category_id, 'integer')        THEN 'category_id non entier'
    WHEN NOT pg_input_is_valid(r.first_listed_on, 'date')       THEN 'first_listed_on n''est pas une date'
    WHEN r.rang > 1 AND r.contenu = r.contenu_1er               THEN 'doublon exact de product_id'
    WHEN r.rang > 1                                             THEN 'conflit : product_id déjà reçu avec un autre contenu'
    WHEN r.rang_sku > 1                                         THEN 'conflit : sku déjà attribué à un autre produit'
    WHEN NOT EXISTS (SELECT 1 FROM nova.categories c WHERE c.category_id = r.category_id::integer)
                                                                THEN 'catégorie inconnue (référence orpheline)'
  END AS motif
FROM (
  SELECT p.*,
         row_number() OVER w AS rang,
         row_number() OVER (PARTITION BY trim(p.sku) ORDER BY p.ligne) AS rang_sku,
         (p.sku, p.product_name, p.category_id, p.first_listed_on)::text AS contenu,
         first_value((p.sku, p.product_name, p.category_id, p.first_listed_on)::text) OVER w AS contenu_1er
  FROM reception.products p
  WINDOW w AS (PARTITION BY trim(p.product_id) ORDER BY p.ligne)
) r;
-- NB : un doublon de product_id a aussi rang_sku > 1, mais le CASE teste
-- d'abord rang (motif le plus précis).

INSERT INTO rejets.journal (source, ligne, cle_source, motif, contenu)
SELECT 'products.csv', ligne, product_id, motif,
       jsonb_build_object('product_id', product_id, 'sku', sku, 'product_name', product_name,
                          'category_id', category_id, 'first_listed_on', first_listed_on)
FROM chk_products WHERE motif IS NOT NULL;

INSERT INTO nova.products (product_id, sku, product_name, category_id, first_listed_on)
SELECT trim(product_id)::integer, trim(sku), trim(product_name),
       category_id::integer, first_listed_on::date
FROM chk_products WHERE motif IS NULL;

-- ---------------------------------------------------------------------
-- 5. Intégrité des liens ventes -> catalogue
--    La FK est d'abord posée NOT VALID (n'impose rien aux lignes S1
--    existantes), puis validée. Si un product_id vendu manquait au
--    catalogue, VALIDATE échouerait et la transaction serait annulée :
--    on contrôle donc la couverture AVANT (voir 11_controles_catalogue.sql).
-- ---------------------------------------------------------------------
\echo '== Produits vendus absents du catalogue (attendu : 0 avant VALIDATE)'
SELECT count(DISTINCT i.product_id) AS produits_vendus_hors_catalogue
FROM nova.order_items i
WHERE NOT EXISTS (SELECT 1 FROM nova.products p WHERE p.product_id = i.product_id);

ALTER TABLE nova.order_items
  ADD CONSTRAINT order_items_product_fk
  FOREIGN KEY (product_id) REFERENCES nova.products (product_id) NOT VALID;
ALTER TABLE nova.order_items VALIDATE CONSTRAINT order_items_product_fk;
CREATE INDEX IF NOT EXISTS order_items_product_id_idx ON nova.order_items (product_id);

-- ---------------------------------------------------------------------
-- 6. Bilan reçus = intégrés + rejetés (avant COMMIT)
-- ---------------------------------------------------------------------
\echo '== Bilan catalogue'
SELECT source, recus, integres, rejetes,
       CASE WHEN recus = integres + rejetes THEN 'OK' ELSE 'KO' END AS bilan
FROM (
  SELECT 'categories.csv' AS source,
         (SELECT count(*) FROM reception.categories) AS recus,
         (SELECT count(*) FROM nova.categories)      AS integres,
         (SELECT count(*) FROM rejets.journal WHERE source = 'categories.csv') AS rejetes
  UNION ALL
  SELECT 'products.csv',
         (SELECT count(*) FROM reception.products),
         (SELECT count(*) FROM nova.products),
         (SELECT count(*) FROM rejets.journal WHERE source = 'products.csv')
) b;

COMMIT;
