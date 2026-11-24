-- =====================================================================
-- 02_import.sql — Réception brute puis intégration métier avec rejets
-- Pré-requis : 01_schema.sql. Exécuter avec psql DANS le conteneur
-- (chemins /s1/donnees/...).
-- Règle : chaque ligne reçue va SOIT dans nova.*, SOIT dans rejets.journal.
-- Doublon d'identifiant : la 1re occurrence (plus petit n° de ligne) est
-- conservée ; les suivantes sont rejetées, en distinguant "doublon exact"
-- (même contenu) et "conflit" (contenu différent).
-- =====================================================================
\set ON_ERROR_STOP 1
BEGIN;

-- ---------------------------------------------------------------------
-- A. RÉCEPTION (copie brute, fichiers sources inchangés)
-- ---------------------------------------------------------------------
\copy reception.customers   (customer_id, customer_name, city)                                FROM '/s1/donnees/customers.csv'   WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy reception.orders      (order_id, customer_id, ordered_on, status)                       FROM '/s1/donnees/orders.csv'      WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\copy reception.order_items (order_item_id, order_id, product_id, quantity, unit_price_cents) FROM '/s1/donnees/order_items.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
-- NDJSON : quote et délimiteur improbables -> chaque ligne arrive entière.
\copy reception.payments    (document) FROM '/s1/donnees/payments.ndjson' WITH (FORMAT csv, QUOTE E'\x01', DELIMITER E'\x02', ENCODING 'UTF8')

-- ---------------------------------------------------------------------
-- B. CUSTOMERS
-- ---------------------------------------------------------------------
CREATE TEMP TABLE chk_customers AS
SELECT r.*,
  CASE
    WHEN NOT pg_input_is_valid(r.customer_id, 'integer') THEN 'customer_id non entier'
    WHEN nullif(trim(r.customer_name), '') IS NULL       THEN 'customer_name manquant'
    WHEN nullif(trim(r.city), '') IS NULL                THEN 'city manquante'
    WHEN r.rang > 1 AND r.contenu = r.contenu_1er        THEN 'doublon exact de customer_id'
    WHEN r.rang > 1                                      THEN 'conflit : customer_id déjà reçu avec un autre contenu'
  END AS motif
FROM (
  SELECT c.*,
         row_number()   OVER w AS rang,
         (c.customer_name, c.city)::text AS contenu,
         first_value((c.customer_name, c.city)::text) OVER w AS contenu_1er
  FROM reception.customers c
  WINDOW w AS (PARTITION BY c.customer_id ORDER BY c.ligne)
) r;

INSERT INTO rejets.journal (source, ligne, cle_source, motif, contenu)
SELECT 'customers.csv', ligne, customer_id, motif,
       jsonb_build_object('customer_id', customer_id, 'customer_name', customer_name, 'city', city)
FROM chk_customers WHERE motif IS NOT NULL;

INSERT INTO nova.customers (customer_id, customer_name, city)
SELECT customer_id::integer, trim(customer_name), trim(city)
FROM chk_customers WHERE motif IS NULL;

-- ---------------------------------------------------------------------
-- C. ORDERS
-- ---------------------------------------------------------------------
CREATE TEMP TABLE chk_orders AS
SELECT r.*,
  CASE
    WHEN NOT pg_input_is_valid(r.order_id, 'integer')    THEN 'order_id non entier'
    WHEN NOT pg_input_is_valid(r.customer_id, 'integer') THEN 'customer_id non entier'
    WHEN NOT pg_input_is_valid(r.ordered_on, 'date')     THEN 'ordered_on n''est pas une date'
    WHEN r.status IS NULL OR r.status NOT IN ('completed', 'pending', 'cancelled')
                                                         THEN 'status inconnu (sensible à la casse)'
    WHEN r.rang > 1 AND r.contenu = r.contenu_1er        THEN 'doublon exact de order_id'
    WHEN r.rang > 1                                      THEN 'conflit : order_id déjà reçu avec un autre contenu'
    WHEN NOT EXISTS (SELECT 1 FROM nova.customers c WHERE c.customer_id = r.customer_id::integer)
                                                         THEN 'client inconnu (référence orpheline)'
  END AS motif
FROM (
  SELECT o.*,
         row_number() OVER w AS rang,
         (o.customer_id, o.ordered_on, o.status)::text AS contenu,
         first_value((o.customer_id, o.ordered_on, o.status)::text) OVER w AS contenu_1er
  FROM reception.orders o
  WINDOW w AS (PARTITION BY o.order_id ORDER BY o.ligne)
) r;

INSERT INTO rejets.journal (source, ligne, cle_source, motif, contenu)
SELECT 'orders.csv', ligne, order_id, motif,
       jsonb_build_object('order_id', order_id, 'customer_id', customer_id, 'ordered_on', ordered_on, 'status', status)
FROM chk_orders WHERE motif IS NOT NULL;

INSERT INTO nova.orders (order_id, customer_id, ordered_on, status)
SELECT order_id::integer, customer_id::integer, ordered_on::date, status
FROM chk_orders WHERE motif IS NULL;

-- ---------------------------------------------------------------------
-- D. ORDER_ITEMS
-- ---------------------------------------------------------------------
CREATE TEMP TABLE chk_items AS
SELECT r.*,
  CASE
    WHEN NOT pg_input_is_valid(r.order_item_id, 'integer')    THEN 'order_item_id non entier'
    WHEN NOT pg_input_is_valid(r.order_id, 'integer')         THEN 'order_id non entier'
    WHEN NOT pg_input_is_valid(r.product_id, 'integer')       THEN 'product_id non entier'
    WHEN CASE WHEN pg_input_is_valid(r.quantity, 'integer')
              THEN r.quantity::integer <= 0 ELSE true END     THEN 'quantity invalide (entier > 0 attendu)'
    WHEN CASE WHEN pg_input_is_valid(r.unit_price_cents, 'integer')
              THEN r.unit_price_cents::integer < 0 ELSE true END THEN 'unit_price_cents invalide'
    WHEN r.rang > 1 AND r.contenu = r.contenu_1er             THEN 'doublon exact de order_item_id'
    WHEN r.rang > 1                                           THEN 'conflit : order_item_id déjà reçu avec un autre contenu'
    WHEN NOT EXISTS (SELECT 1 FROM nova.orders o WHERE o.order_id = r.order_id::integer)
                                                              THEN 'commande inconnue (référence orpheline)'
  END AS motif
FROM (
  SELECT i.*,
         row_number() OVER w AS rang,
         (i.order_id, i.product_id, i.quantity, i.unit_price_cents)::text AS contenu,
         first_value((i.order_id, i.product_id, i.quantity, i.unit_price_cents)::text) OVER w AS contenu_1er
  FROM reception.order_items i
  WINDOW w AS (PARTITION BY i.order_item_id ORDER BY i.ligne)
) r;

INSERT INTO rejets.journal (source, ligne, cle_source, motif, contenu)
SELECT 'order_items.csv', ligne, order_item_id, motif,
       jsonb_build_object('order_item_id', order_item_id, 'order_id', order_id, 'product_id', product_id,
                          'quantity', quantity, 'unit_price_cents', unit_price_cents)
FROM chk_items WHERE motif IS NOT NULL;

INSERT INTO nova.order_items (order_item_id, order_id, product_id, quantity, unit_price_cents)
SELECT order_item_id::integer, order_id::integer, product_id::integer, quantity::integer, unit_price_cents::integer
FROM chk_items WHERE motif IS NULL;

-- ---------------------------------------------------------------------
-- E. PAYMENTS (NDJSON)
--    Attention : deux paiements de même montant sur une même commande ne
--    sont PAS des doublons (paiement fractionné) -> seul payment_id fait foi.
-- ---------------------------------------------------------------------
CREATE TEMP TABLE chk_payments AS
WITH parse AS (
  SELECT p.ligne, p.document,
         pg_input_is_valid(p.document, 'jsonb') AS json_ok
  FROM reception.payments p
), champs AS (
  SELECT ligne, document, json_ok,
         CASE WHEN json_ok THEN document::jsonb ->> 'payment_id'   END AS payment_id,
         CASE WHEN json_ok THEN document::jsonb ->> 'order_id'     END AS order_id,
         CASE WHEN json_ok THEN document::jsonb ->> 'paid_on'      END AS paid_on,
         CASE WHEN json_ok THEN document::jsonb ->> 'amount_cents' END AS amount_cents,
         CASE WHEN json_ok THEN document::jsonb ->> 'status'       END AS status
  FROM parse
)
SELECT r.*,
  CASE
    WHEN NOT r.json_ok                                     THEN 'JSON invalide'
    WHEN NOT pg_input_is_valid(r.payment_id, 'integer')    THEN 'payment_id absent ou non entier'
    WHEN NOT pg_input_is_valid(r.order_id, 'integer')      THEN 'order_id absent ou non entier'
    WHEN NOT pg_input_is_valid(r.paid_on, 'date')          THEN 'paid_on absent ou non date'
    WHEN CASE WHEN pg_input_is_valid(r.amount_cents, 'integer')
              THEN r.amount_cents::integer <= 0 ELSE true END THEN 'amount_cents invalide (entier > 0 attendu)'
    WHEN r.status IS NULL OR r.status NOT IN ('captured', 'pending')
                                                           THEN 'status inconnu (sensible à la casse)'
    WHEN r.rang > 1 AND r.contenu = r.contenu_1er          THEN 'doublon exact de payment_id'
    WHEN r.rang > 1                                        THEN 'conflit : payment_id déjà reçu avec un autre contenu'
    WHEN NOT EXISTS (SELECT 1 FROM nova.orders o WHERE o.order_id = r.order_id::integer)
                                                           THEN 'commande inconnue (référence orpheline)'
  END AS motif
FROM (
  SELECT c.*,
         row_number() OVER w AS rang,
         (c.order_id, c.paid_on, c.amount_cents, c.status)::text AS contenu,
         first_value((c.order_id, c.paid_on, c.amount_cents, c.status)::text) OVER w AS contenu_1er
  FROM champs c
  WINDOW w AS (PARTITION BY c.payment_id ORDER BY c.ligne)
) r;

INSERT INTO rejets.journal (source, ligne, cle_source, motif, contenu)
SELECT 'payments.ndjson', ligne, payment_id, motif,
       CASE WHEN json_ok THEN document::jsonb ELSE to_jsonb(document) END
FROM chk_payments WHERE motif IS NOT NULL;

INSERT INTO nova.payments (payment_id, order_id, paid_on, amount_cents, status)
SELECT payment_id::integer, order_id::integer, paid_on::date, amount_cents::integer, status
FROM chk_payments WHERE motif IS NULL;

COMMIT;
