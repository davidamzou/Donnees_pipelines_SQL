-- =====================================================================
-- 06_normalisation.sql — Anomalies d'insertion / mise à jour / suppression
-- sur l'exemple indépendant planning_a_normaliser.csv, puis version normalisée.
-- Tout se fait dans une transaction annulée : aucune trace en base.
-- =====================================================================
\set ON_ERROR_STOP 1
BEGIN;

CREATE TEMP TABLE planning (
    reservation_id integer PRIMARY KEY,
    salle_id       integer NOT NULL,
    salle_nom      text    NOT NULL,
    responsable    text    NOT NULL
);
\copy planning FROM '/s1/exemple/planning_a_normaliser.csv' WITH (FORMAT csv, HEADER true)

\echo '== Table redondante : nom et responsable répétés à chaque réservation'
SELECT * FROM planning ORDER BY reservation_id;

-- 1. Anomalie de MISE À JOUR : on ne modifie qu'une ligne -> incohérence
\echo '== 1. Mise à jour partielle : Ariane est remplacée par Lina, sur une seule ligne'
UPDATE planning SET responsable = 'Lina' WHERE reservation_id = 1;
SELECT salle_id, array_agg(DISTINCT responsable) AS responsables_contradictoires
FROM planning GROUP BY salle_id HAVING count(DISTINCT responsable) > 1;

-- 2. Anomalie d'INSERTION : impossible d'enregistrer une salle sans réservation
\echo '== 2. Insertion : la salle 3 (Atelier Photo) n''a aucune réservation'
SAVEPOINT avant_insertion;
\set ON_ERROR_STOP 0
INSERT INTO planning (reservation_id, salle_id, salle_nom, responsable)
VALUES (NULL, 3, 'Atelier Photo', 'Noé');   -- échoue : reservation_id obligatoire
\set ON_ERROR_STOP 1
ROLLBACK TO SAVEPOINT avant_insertion;

-- 3. Anomalie de SUPPRESSION : supprimer la dernière réservation efface la salle
\echo '== 3. Suppression : on supprime l''unique réservation de la salle 2'
DELETE FROM planning WHERE reservation_id = 3;
SELECT count(*) AS lignes_restantes_sur_salle_2,
       'nom et responsable de la salle 2 perdus' AS consequence
FROM planning WHERE salle_id = 2;

-- Solution : séparer l'entité salle de l'entité réservation (3NF)
\echo '== Version normalisée : salle (1) --- (N) reservation'
CREATE TEMP TABLE salle (
    salle_id    integer PRIMARY KEY,
    salle_nom   text NOT NULL,
    responsable text NOT NULL
);
CREATE TEMP TABLE reservation (
    reservation_id integer PRIMARY KEY,
    salle_id       integer NOT NULL REFERENCES salle (salle_id)
);
INSERT INTO salle VALUES (1, 'Atelier Céramique', 'Ariane'), (2, 'Atelier Textile', 'Sam'),
                         (3, 'Atelier Photo', 'Noé');          -- insertion possible sans réservation
INSERT INTO reservation VALUES (1, 1), (2, 1), (3, 2);
UPDATE salle SET responsable = 'Lina' WHERE salle_id = 1;      -- une seule ligne à modifier
DELETE FROM reservation WHERE reservation_id = 3;              -- la salle 2 survit
SELECT s.salle_id, s.salle_nom, s.responsable, count(r.reservation_id) AS reservations
FROM salle s LEFT JOIN reservation r USING (salle_id)
GROUP BY s.salle_id ORDER BY s.salle_id;

ROLLBACK;
