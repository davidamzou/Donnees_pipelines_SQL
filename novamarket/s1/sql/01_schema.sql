-- =====================================================================
-- 01_schema.sql — Schémas de réception, de rejets et métier (NovaMarket S1)
-- Rejouable : supprime puis recrée les trois schémas.
-- =====================================================================
\set ON_ERROR_STOP 1
BEGIN;

DROP SCHEMA IF EXISTS nova      CASCADE;
DROP SCHEMA IF EXISTS rejets    CASCADE;
DROP SCHEMA IF EXISTS reception CASCADE;

-- ---------------------------------------------------------------------
-- 1. RÉCEPTION : copie brute des fichiers, tout en text, aucune contrainte.
--    -> rien n'est perdu à l'import, chaque ligne garde son numéro source.
-- ---------------------------------------------------------------------
CREATE SCHEMA reception;

CREATE TABLE reception.customers (
    ligne         bigint GENERATED ALWAYS AS IDENTITY,  -- n° de ligne de données (hors en-tête)
    customer_id   text,
    customer_name text,
    city          text
);
CREATE TABLE reception.orders (
    ligne       bigint GENERATED ALWAYS AS IDENTITY,
    order_id    text,
    customer_id text,
    ordered_on  text,
    status      text
);
CREATE TABLE reception.order_items (
    ligne            bigint GENERATED ALWAYS AS IDENTITY,
    order_item_id    text,
    order_id         text,
    product_id       text,
    quantity         text,
    unit_price_cents text
);
-- NDJSON : une ligne = un document, stocké en text pour ne pas
-- faire échouer tout l'import sur un JSON mal formé.
CREATE TABLE reception.payments (
    ligne    bigint GENERATED ALWAYS AS IDENTITY,
    document text
);

-- ---------------------------------------------------------------------
-- 2. REJETS : journal unique, une ligne par enregistrement écarté + cause.
-- ---------------------------------------------------------------------
CREATE SCHEMA rejets;

CREATE TABLE rejets.journal (
    rejet_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source     text   NOT NULL,          -- fichier d'origine
    ligne      bigint NOT NULL,          -- n° de ligne de données dans la source
    cle_source text,                     -- identifiant tel que reçu
    motif      text   NOT NULL,          -- cause du rejet
    contenu    jsonb  NOT NULL,          -- ligne brute complète
    rejete_le  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 3. MÉTIER : données typées et contraintes. Ordre d'import imposé par
--    les clés étrangères : customers -> orders -> order_items / payments.
-- ---------------------------------------------------------------------
CREATE SCHEMA nova;

CREATE TABLE nova.customers (
    customer_id   integer PRIMARY KEY,
    customer_name text NOT NULL,
    city          text NOT NULL
);

CREATE TABLE nova.orders (
    order_id    integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES nova.customers (customer_id),
    ordered_on  date    NOT NULL,
    status      text    NOT NULL CHECK (status IN ('completed', 'pending', 'cancelled'))
);
CREATE INDEX ON nova.orders (customer_id);

CREATE TABLE nova.order_items (
    order_item_id    integer PRIMARY KEY,
    order_id         integer NOT NULL REFERENCES nova.orders (order_id),
    product_id       integer NOT NULL,   -- pas de FK : catalogue hors périmètre S1
    quantity         integer NOT NULL CHECK (quantity > 0),
    unit_price_cents integer NOT NULL CHECK (unit_price_cents >= 0)
);
CREATE INDEX ON nova.order_items (order_id);

CREATE TABLE nova.payments (
    payment_id   integer PRIMARY KEY,
    order_id     integer NOT NULL REFERENCES nova.orders (order_id),
    paid_on      date    NOT NULL,
    amount_cents integer NOT NULL CHECK (amount_cents > 0),
    status       text    NOT NULL CHECK (status IN ('captured', 'pending'))
);
CREATE INDEX ON nova.payments (order_id);

COMMIT;
