-- =====================================================================
-- 00_connexion.sql — M2 : preuve que la pile est démarrée et accessible
-- =====================================================================
\set ON_ERROR_STOP 1
\echo '== Test de connexion'
SELECT current_database() AS base, current_user AS utilisateur,
       split_part(version(), ' ', 2) AS version_postgresql, now() AS horodatage;
