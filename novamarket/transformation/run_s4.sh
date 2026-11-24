#!/usr/bin/env bash
# S4 · Rejoue le chargement PostgreSQL et la chaîne dbt, écrit les preuves dans
# transformation/resultats/. À lancer depuis novamarket/ (ou n'importe où).
#
# Secrets saisis dans la session, jamais dans un fichier :
#   read -rs PGPASSWORD; echo; export PGPASSWORD DBT_ENV_SECRET_PASSWORD="$PGPASSWORD"
#   ./transformation/run_s4.sh                  # chargement + rejeu + dbt
#   ./transformation/run_s4.sh --reinitialiser  # supprime d'abord fournisseur et dbt_dev_*
#
# Utilise les services Compose `chargeur` et `dbt` (profil transfo) : aucun
# Python local n'est nécessaire.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${PGPASSWORD:?exporter PGPASSWORD : read -rs PGPASSWORD; export PGPASSWORD}"
: "${DBT_ENV_SECRET_PASSWORD:?exporter DBT_ENV_SECRET_PASSWORD (même mot de passe local)}"
export DBT_DATABASE="${DBT_DATABASE:-novamarket}"
R=transformation/resultats
mkdir -p "$R"

# s4/travail/ est ignoré par Git (s4/.gitignore) : sur un clone neuf, créer le
# profil depuis l'exemple sans secret (le mot de passe reste dans la session).
if [[ ! -f s4/travail/profil/profiles.yml ]]; then
  mkdir -p s4/travail/profil
  cp transformation/dbt/profiles.exemple.yml s4/travail/profil/profiles.yml
  echo "Profil dbt créé : s4/travail/profil/profiles.yml (copie de profiles.exemple.yml)"
fi

psql_() { docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U atelier -d "$DBT_DATABASE" "$@"; }
charger() { docker compose --profile transfo run --rm -e PGPASSWORD chargeur "$@" 2>/dev/null; }
dbt_() {
  docker compose --profile transfo run --rm --no-deps --user "$(id -u):$(id -g)" -w /projet \
    -e DBT_ENV_SECRET_PASSWORD -e DBT_DATABASE -e DBT_USE_COLORS=false dbt \
    dbt "$@" --profiles-dir /work/profil 2>&1 | grep -vE 'dbt v2 is available|install-dbt|upgrading-to-v2'
}
comptages() {
  psql_ -At -c "SELECT 'offres en base : ' || count(*) || ' (dont observées le 23/11 : '
                || count(*) FILTER (WHERE observed_on = DATE '2026-11-23') || ')' FROM fournisseur.offres;"
}

docker compose up -d --wait postgres >/dev/null
docker compose --profile transfo build chargeur dbt >/dev/null

if [[ "${1:-}" == "--reinitialiser" ]]; then
  psql_ -q -c "SET client_min_messages = warning;" -c "DROP SCHEMA IF EXISTS dbt_dev_marts, dbt_dev_intermediate, dbt_dev_staging, fournisseur CASCADE;"
  echo "Schémas fournisseur et dbt_dev_* supprimés."
fi

echo "== M1 · premier chargement puis rejeu du même lot"
{
  echo "### Premier chargement"; charger; comptages
  echo; echo "### Rejeu du même fichier"; charger; comptages
} | tee "$R/01_chargement_et_rejeu.txt"

echo "== M1 · atomicité : panne après 1 écriture sur un lot qui insère"
{
  echo "### Avant"; comptages
  echo; echo "### Lot jour_precedent.jsonl, panne simulée après la 1re écriture"
  charger --fichier transformation/exemple_lots/jour_precedent.jsonl --echouer-apres 1 || echo "(code de sortie $? attendu : lot annulé)"
  echo; echo "### Après"; comptages
} | tee "$R/02_atomicite.txt"

echo "== M1 · essais (exécutés puis annulés) : autre jour, correction, lot défectueux"
{
  for f in jour_precedent correction_prix defectueux; do
    echo "### --essai exemple_lots/$f.jsonl"; charger --fichier "transformation/exemple_lots/$f.jsonl" --essai; echo
  done
  comptages
} | tee "$R/03_essais.txt"

echo "== M1 · journal des lots"
psql_ -c "SELECT lot_id, statut, lignes_lues AS lues, inserees, mises_a_jour, reutilisees, rejetees,
                 coalesce(run_s3, fichier) AS source, erreur
          FROM fournisseur.lots ORDER BY lot_id;" \
      -c "SELECT lot_id, action, count(*) FROM fournisseur.lot_lignes GROUP BY 1, 2 ORDER BY 1, 2;" \
  | tee "$R/04_lots.txt"

echo "== M2–M5 · dbt compile, run, build"
{
  echo "### dbt compile"; dbt_ compile
  echo; echo "### dbt run"; dbt_ run
  echo; echo "### dbt build"; dbt_ build
} > "$R/05_dbt.txt"
grep -E "Done\.|ERROR|FAIL" "$R/05_dbt.txt"
cp transformation/dbt/target/compiled/novamarket_dbt/models/marts/mart_offres_par_produit.sql \
   "$R/06_mart_offres_par_produit.compile.sql"

echo "== M5 · volumes par couche et contenu du mart"
psql_ < transformation/sql/verifications_s4.sql | tee "$R/07_volumes_et_mart.txt"
echo "Preuves écrites dans $R/"
