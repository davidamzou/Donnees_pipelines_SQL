#!/usr/bin/env bash
# Rejoue le benchmark S3 depuis novamarket/ : ./s3/sql/run_s3.sh
# Pré-requis : schéma benchmark généré (s3/generer.sql, 10 M lignes).
# Protocole : pour chaque requête, 1 premier passage (après redémarrage de
# PostgreSQL = tampons partagés vides) isolé, puis 3 répétitions ; on retient
# la médiane des 3 répétitions. Plans complets dans s3/resultats/plans/.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=s3/resultats; PLANS=$OUT/plans; mkdir -p "$PLANS"
REPS=${REPS:-3}
psql_run() { docker compose exec -T postgres psql -X -q -v ON_ERROR_STOP=1 -U atelier -d novamarket "$@"; }
restart_pg() { docker compose restart postgres >/dev/null 2>&1; docker compose up -d --wait postgres >/dev/null 2>&1; }

MESURES=$OUT/mesures.csv
[ -f "$MESURES" ] || echo "phase,requete,passage,execution_ms,planning_ms,shared_hit,shared_read,noeud_principal" > "$MESURES"

bench() { # phase requete
  local phase=$1 q=$2 f="s3/sql/requetes/$2.sql"
  restart_pg
  for i in $(seq 0 "$REPS"); do
    local plan="$PLANS/${phase}_${q}_run${i}.txt"
    psql_run < "$f" > "$plan"
    local ex pl hit rd node
    # Compteurs BUFFERS lus sur la 1re ligne « Buffers: » (nœud racine, inclut les enfants)
    local buf; buf=$(grep -m1 'Buffers:' "$plan" || true)
    ex=$(grep -o 'Execution Time: [0-9.]*' "$plan" | awk '{print $3}' || true)
    pl=$(grep -o 'Planning Time: [0-9.]*' "$plan" | awk '{print $3}' || true)
    hit=$(grep -o 'hit=[0-9]*' <<<"$buf" | cut -d= -f2 || true); hit=${hit:-0}
    rd=$(grep -o 'read=[0-9]*' <<<"$buf" | cut -d= -f2 || true); rd=${rd:-0}
    node=$(grep -E -o '(Parallel )?(Seq Scan|Index Only Scan|Index Scan|Bitmap Heap Scan)' "$plan" | head -1 || true)
    local label=$i; [ "$i" = 0 ] && label="premier"
    echo "$phase,$q,$label,$ex,$pl,$hit,$rd,$node" | tee -a "$MESURES"
  done
}

echo "################ 20_contexte_volume"
psql_run < s3/sql/20_contexte_volume.sql | tee $OUT/20_contexte_volume.txt

echo "################ M1 référence sans index"
psql_run -c "DROP INDEX IF EXISTS benchmark.benchmark_sales_store_id_idx;"
bench avant_index QA_selectif
bench avant_index QB_large

echo "################ M2 création de l'index"
psql_run < s3/sql/21_index.sql | tee $OUT/21_index.txt
bench apres_index QA_selectif
bench apres_index QB_large
bench apres_index QB_force_index

echo "################ M3 estimations et multiplication"
psql_run < s3/sql/22_estimations.sql > $OUT/22_estimations.txt
psql_run < s3/sql/23_multiplication.sql > $OUT/23_multiplication.txt

echo "################ Synthèse (médiane des répétitions, premier passage exclu)"
python3 -I s3/sql/synthese.py "$MESURES" | tee $OUT/synthese.md
