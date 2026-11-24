-- S4 · Schéma fournisseur, séparé de nova (S1–S2) et des schémas dbt.
-- Rejouable : exécuté par chargement_postgres.py au début de chaque transaction.
--
-- Grain de fournisseur.offres : UNE OFFRE OBSERVÉE UN JOUR DONNÉ.
-- Clé (offer_id, observed_on) : une même offre peut être observée plusieurs
-- jours sans doublon, et un rejeu du même jour retombe sur la même ligne.

CREATE SCHEMA IF NOT EXISTS fournisseur;

-- Référentiel des fournisseurs autorisés (contrat S3 : F01, F02, F03).
CREATE TABLE IF NOT EXISTS fournisseur.fournisseurs (
    supplier_id   text PRIMARY KEY CHECK (supplier_id ~ '^F[0-9]{2}$'),
    supplier_name text NOT NULL
);
INSERT INTO fournisseur.fournisseurs (supplier_id, supplier_name) VALUES
    ('F01', 'Fournisseur simulé 01'),
    ('F02', 'Fournisseur simulé 02'),
    ('F03', 'Fournisseur simulé 03')
ON CONFLICT (supplier_id) DO NOTHING;

-- Un lot = une exécution du chargeur. Les compteurs sont contraints :
-- lues = acceptées + rejetées ; acceptées = insérées + mises à jour + réutilisées.
CREATE TABLE IF NOT EXISTS fournisseur.lots (
    lot_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fichier       text        NOT NULL,
    sha256        char(64)    NOT NULL,
    run_s3        text,
    demarre_le    timestamptz NOT NULL DEFAULT clock_timestamp(),
    termine_le    timestamptz,
    statut        text        NOT NULL CHECK (statut IN ('en_cours', 'termine', 'annule')),
    lignes_lues   integer     NOT NULL DEFAULT 0,
    acceptees     integer     NOT NULL DEFAULT 0,
    inserees      integer     NOT NULL DEFAULT 0,
    mises_a_jour  integer     NOT NULL DEFAULT 0,
    reutilisees   integer     NOT NULL DEFAULT 0,
    rejetees      integer     NOT NULL DEFAULT 0,
    erreur        text,
    CHECK (lignes_lues = acceptees + rejetees),
    CHECK (acceptees = inserees + mises_a_jour + reutilisees)
);

CREATE TABLE IF NOT EXISTS fournisseur.offres (
    offer_id        text    NOT NULL CHECK (offer_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    observed_on     date    NOT NULL,
    supplier_id     text    NOT NULL REFERENCES fournisseur.fournisseurs (supplier_id),
    product_id      integer NOT NULL,
    price_cents     integer NOT NULL CHECK (price_cents >= 0),
    currency        char(3) NOT NULL CHECK (currency = 'EUR'),
    available_units integer NOT NULL CHECK (available_units >= 0),
    lot_insertion   bigint  NOT NULL REFERENCES fournisseur.lots (lot_id),
    lot_maj         bigint  NOT NULL REFERENCES fournisseur.lots (lot_id),
    insere_le       timestamptz NOT NULL DEFAULT clock_timestamp(),
    maj_le          timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (offer_id, observed_on)
);
CREATE INDEX IF NOT EXISTS offres_product_id_idx  ON fournisseur.offres (product_id);
CREATE INDEX IF NOT EXISTS offres_supplier_id_idx ON fournisseur.offres (supplier_id);

-- Référence produit vers le catalogue S2. Posée à part : un `DROP SCHEMA nova
-- CASCADE` (run_all.sh S1) la supprime ; elle est alors recréée ici.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'offres_product_fk'
                     AND conrelid = 'fournisseur.offres'::regclass) THEN
        ALTER TABLE fournisseur.offres
            ADD CONSTRAINT offres_product_fk
            FOREIGN KEY (product_id) REFERENCES nova.products (product_id);
    END IF;
END $$;

-- Trace ligne à ligne de chaque lot : ce qui a été inséré, mis à jour,
-- réutilisé (déjà présent à l'identique) ou rejeté, et pourquoi.
CREATE TABLE IF NOT EXISTS fournisseur.lot_lignes (
    lot_id       bigint  NOT NULL REFERENCES fournisseur.lots (lot_id),
    numero_ligne integer NOT NULL CHECK (numero_ligne >= 1),
    offer_id     text,
    observed_on  date,
    action       text    NOT NULL CHECK (action IN ('inseree', 'mise_a_jour', 'reutilisee', 'rejetee')),
    motifs       text[],
    ligne_brute  text,
    PRIMARY KEY (lot_id, numero_ligne),
    CHECK ((action = 'rejetee') = (motifs IS NOT NULL))
);
