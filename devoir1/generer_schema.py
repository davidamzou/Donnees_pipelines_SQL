"""Génère le schéma d'architecture NovaMarket au format .drawio (diagrams.net)."""
import base64
import html
import sys
import urllib.parse
import zlib

OUT = sys.argv[1]
URL_OUT = sys.argv[2]

cells = []
_n = [0]


def nid(prefix="c"):
    _n[0] += 1
    return f"{prefix}{_n[0]}"


def esc(s):
    return html.escape(s, quote=True)


# ---------- styles ----------
KIND = {
    "src": "fillColor=#fff2cc;strokeColor=#d6b656;",
    "ing": "fillColor=#ffe6cc;strokeColor=#d79b00;",
    "sto": "fillColor=#d5e8d4;strokeColor=#82b366;",
    "trf": "fillColor=#e1d5e7;strokeColor=#9673a6;",
    "res": "fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "ext": "fillColor=#f5f5f5;strokeColor=#666666;",
    "orc": "fillColor=#ffffff;strokeColor=#999999;dashed=1;",
    "note": "fillColor=#ffffff;strokeColor=none;",
}
BASE = "rounded=1;whiteSpace=wrap;html=1;arcSize=6;fontSize=11;align=left;verticalAlign=top;spacingLeft=6;spacingTop=2;spacingRight=4;fontFamily=Helvetica;"
EDGE = {
    "data": "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#0b6bcb;strokeWidth=2.5;endArrow=block;endFill=1;fontSize=10;fontColor=#0b4f96;labelBackgroundColor=#ffffff;",
    "rej": "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#c0392b;strokeWidth=2;endArrow=block;endFill=1;fontSize=10;fontColor=#c0392b;labelBackgroundColor=#ffffff;",
    "tech": "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#6e6e6e;strokeWidth=1.4;dashed=1;dashPattern=6 4;endArrow=open;endFill=0;fontSize=10;fontColor=#444444;labelBackgroundColor=#ffffff;",
    "dep": "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#0b6bcb;strokeWidth=2;dashed=1;dashPattern=2 3;endArrow=block;endFill=1;fontSize=10;fontColor=#0b4f96;labelBackgroundColor=#ffffff;",
}


def vertex(label, x, y, w, h, style, cid=None):
    cid = cid or nid()
    cells.append(
        f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )
    return cid


def box(label, x, y, w, h, kind, cid=None, extra=""):
    return vertex(label, x, y, w, h, BASE + KIND[kind] + extra, cid)


def cyl(label, x, y, w, h, cid=None):
    st = ("shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=8;fontSize=11;"
          "align=left;verticalAlign=top;spacingLeft=6;spacingTop=4;" + KIND["sto"])
    return vertex(label, x, y, w, h, st, cid)


def doc(label, x, y, w, h, cid=None, kind="sto"):
    st = ("shape=note;whiteSpace=wrap;html=1;size=12;fontSize=11;align=left;verticalAlign=top;"
          "spacingLeft=6;spacingTop=2;" + KIND[kind])
    return vertex(label, x, y, w, h, st, cid)


def cloud(label, x, y, w, h, cid=None):
    st = "ellipse;shape=cloud;whiteSpace=wrap;html=1;fontSize=11;" + KIND["ext"]
    return vertex(label, x, y, w, h, st, cid)


def frame(label, x, y, w, h, kind="docker", cid=None):
    if kind == "docker":
        st = ("rounded=1;arcSize=3;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#1f6feb;strokeWidth=2;"
              "fillColor=#f3f8ff;verticalAlign=top;align=left;spacingLeft=8;spacingTop=2;fontSize=11;fontColor=#1f4e9e;")
    elif kind == "local":
        st = ("rounded=1;arcSize=3;whiteSpace=wrap;html=1;dashed=1;dashPattern=1 3;strokeColor=#555555;strokeWidth=2;"
              "fillColor=#fafafa;verticalAlign=top;align=left;spacingLeft=8;spacingTop=2;fontSize=11;fontColor=#333333;")
    elif kind == "planned":
        st = ("rounded=1;arcSize=3;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#9e9e9e;strokeWidth=2;"
              "fillColor=#f7f7f7;verticalAlign=top;align=left;spacingLeft=8;spacingTop=2;fontSize=11;fontColor=#777777;")
    return vertex(label, x, y, w, h, st, cid)


def lane(label, x, y, w, h, fill):
    st = (f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor=#c8c8c8;verticalAlign=top;align=left;"
          "spacingLeft=10;spacingTop=4;fontSize=13;fontColor=#222222;")
    return vertex(label, x, y, w, h, st)


def text(label, x, y, w, h, extra=""):
    st = "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align=left;verticalAlign=top;fontSize=11;" + extra
    return vertex(label, x, y, w, h, st)


def edge(src, tgt, kind="data", label="", pts=None, extra="", lx=None):
    cid = nid("e")
    lxa = "" if lx is None else 'x="%s" ' % lx
    geo = '<mxGeometry ' + lxa + 'relative="1" as="geometry">'
    if pts:
        geo += '<Array as="points">' + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in pts) + "</Array>"
    geo += "</mxGeometry>"
    cells.append(
        f'<mxCell id="{cid}" value="{esc(label)}" style="{EDGE[kind]}{extra}" edge="1" parent="1" '
        f'source="{src}" target="{tgt}">{geo}</mxCell>'
    )
    return cid


def T(title, *lines, tag=None):
    """Libellé HTML : titre gras + lignes secondaires (petite police)."""
    title = title.replace("<run>", "&lt;run&gt;")
    lines = [l.replace("<run>", "&lt;run&gt;") for l in lines]
    s = f"<b>{title}</b>"
    if tag:
        s = f'<font style="font-size:9px" color="#1f4e9e"><b>{tag}</b></font><br>' + s
    if lines:
        s += '<br><font style="font-size:10px">' + "<br>".join(lines) + "</font>"
    return s


def LIB(*libs):
    return '<i><font color="#7a3e9d">' + " · ".join(libs) + "</font></i>"


# ---------- géométrie ----------
C1, W1 = 40, 330      # Sources
C2, W2 = 410, 420     # Ingestion & validation
C3, W3 = 870, 560     # Stockage
C4, W4 = 1470, 430    # Transformations
C5, W5 = 1940, 340    # Restitution
LEG = 2330
FILES_X, FILES_W = 880, 230
PG_X, PG_W = 1165, 270

# ---------- titre ----------
text('<font style="font-size:24px"><b>NovaMarket — Cartographie de l\'architecture et des flux de données (S1 → S5)</b></font>'
     '<br><font style="font-size:13px" color="#555555">Devoir 1 · Ingénierie des données et pipelines SQL · Mastère 1 IA &amp; Data — Ynov Campus'
     ' · Groupe : ____________________ · Dépôt : Donnees_pipelines_SQL (novamarket/)</font>',
     C1, 8, 2200, 60)

# ---------- couloirs (branches) ----------
lane('<b>BRANCHE 1 · Transactionnel NovaMarket (S1 → S2)</b> <font style="font-size:11px" color="#555">— séquentielle : run_all.sh (S1) puis run_s2.sh (S2) ; S2 s\'appuie sur les schémas reception / rejets / nova créés en S1</font>',
     20, 110, 2280, 420, "#fffdf5")
lane('<b>BRANCHE 2 · Benchmark S3 (10 M lignes)</b> <font style="font-size:11px" color="#555">— <b>INDÉPENDANTE</b> : données générées par generate_series, schéma benchmark isolé ; ne lit aucune table NovaMarket</font>',
     20, 540, 2280, 220, "#f7fbff")
lane('<b>BRANCHE 3 · Offres fournisseurs (S3 ingestion → S4 chargement + dbt)</b> <font style="font-size:11px" color="#555">— collecte indépendante de PostgreSQL ; le chargement et dbt <b>dépendent de la branche 1</b> (nova.products, nova.orders / order_items)</font>',
     20, 770, 2280, 490, "#fffdf5")
lane('<b>BRANCHE 4 · Volumétrie S5 (Hugging Face → contrôle qualité → Spark → Hub)</b> <font style="font-size:11px" color="#555">— <b>INDÉPENDANTE</b> de PostgreSQL et des branches 1 à 3</font>',
     20, 1270, 2280, 460, "#f7fbff")

# ---------- en-têtes de colonnes ----------
HDR = "rounded=1;whiteSpace=wrap;html=1;fontSize=13;fontStyle=1;align=center;verticalAlign=middle;arcSize=20;"
vertex("① SOURCES", C1, 72, W1, 30, HDR + KIND["src"])
vertex("② INGESTION &amp; VALIDATION".replace("&amp;", "&"), C2, 72, W2, 30, HDR + KIND["ing"])
vertex("③ STOCKAGE", C3, 72, W3, 30, HDR + KIND["sto"])
vertex("④ TRAITEMENTS &amp; TRANSFORMATIONS".replace("&amp;", "&"), C4, 72, W4, 30, HDR + KIND["trf"])
vertex("⑤ RESTITUTION", C5, 72, W5, 30, HDR + KIND["res"])

# ================= PostgreSQL (stockage partagé branches 1-3) =================
frame(T("DOCKER · service postgres", "postgres:17.12-bookworm · base novamarket · toujours actif"),
      PG_X - 10, 140, PG_W + 20, 1110, "docker")
pg_rec = cyl(T("schéma reception", "Zone d'atterrissage brute (TEXT)", "customers · orders · order_items", "payments (document NDJSON) · categories · products"),
             PG_X, 185, PG_W, 95)
pg_rej = cyl(T("schéma rejets", "rejets.journal : source, ligne, clé, motif,", "contenu jsonb (traçabilité des refus)"),
             PG_X, 292, PG_W, 70)
pg_nova = cyl(T("schéma nova (modèle typé)", "customers · orders · order_items · payments", "categories (hiérarchie) · products", "PK / FK / CHECK"),
              PG_X, 375, PG_W, 100)
pg_bench = cyl(T("schéma benchmark", "benchmark_sales : 10 000 000 lignes", "campaign_assignments", "index benchmark_sales_store_id_idx (S3)"),
               PG_X, 580, PG_W, 100)
pg_four = cyl(T("schéma fournisseur", "fournisseurs (référentiel F01–F03)", "offres — PK (offer_id, observed_on)", "lots (compteurs, statut) · lot_lignes (action par ligne)"),
              PG_X, 820, PG_W, 105)
pg_dbt = cyl(T("schémas dbt_dev_*", "dbt_dev_staging (vues) · dbt_dev_intermediate (vues)", "dbt_dev_marts.mart_offres_par_produit (table)",
                "← matérialisés par dbt (CREATE VIEW / TABLE, TCP 5432)"),
             PG_X, 945, PG_W, 95)
box(T("Infrastructure", "volume nommé <b>postgres_data</b> → /var/lib/postgresql/data",
      "bind ./s1 → /s1 (lecture seule)", "port 127.0.0.1:15432 → 5432 · 2 CPU / 2 Go",
      "healthcheck pg_isready · réseau Compose (hôte « postgres »)"),
    PG_X, 1145, PG_W, 95, "ext")

# ================= BRANCHE 1 =================
f_s1 = frame(T("LOCAL · dépôt Git (fichiers sources)"), C1 - 5, 140, W1 + 10, 380, "local")
s1csv = doc(T("s1/donnees/*.csv", "customers.csv · orders.csv · order_items.csv", "CSV UTF-8 avec anomalies volontaires"),
            C1 + 5, 170, W1 - 10, 70, kind="src")
s1json = doc(T("s1/donnees/payments.ndjson", "1 document JSON par ligne (lignes invalides incluses)"),
             C1 + 5, 250, W1 - 10, 55, kind="src")
s2csv = doc(T("s2/donnees/categories.csv · products.csv", "catalogue S2 (brut, non modifié ;", "doublon exact product_id = 3)"),
            C1 + 5, 315, W1 - 10, 65, kind="src")
text('<font style="font-size:10px" color="#555">• s1/ monté en lecture seule sur /s1 du conteneur postgres<br>'
     '• s2/donnees copié par <i>docker compose cp</i> → /tmp/novamarket-s2<br>'
     '• s1/exemple/ (ateliers culturels) : exemple 3FN isolé (06_normalisation)</font>',
     C1 + 5, 390, W1 - 10, 60)

f_psql = frame(T("DOCKER · exécuté dans postgres via psql", "lancé depuis l'hôte : docker compose exec -T postgres psql -v ON_ERROR_STOP=1"),
               C2 - 5, 140, W2 + 10, 380, "docker")
ing_imp = box(T("Import brut (\\copy)", "02_import.sql (S1) · 10_catalogue.sql (S2)",
                "fichiers → reception.* en TEXT, sans transformation", "payments.ndjson lu ligne par ligne (document)"),
              C2 + 5, 185, W2 - 10, 80, "ing")
ing_ctl = box(T("Typage, contrôles et rejets motivés", "02_import · 03_controles · 10/11_controles_catalogue",
                "pg_input_is_valid(), casts, jsonb ->>, unicité, FK, dates, montants",
                "valides → nova.* · invalides → rejets.journal (motif + contenu)"),
              C2 + 5, 280, W2 - 10, 95, "ing")
orc1 = box(T("Orchestration (LOCAL · bash)", "s1/sql/run_all.sh : 00_connexion → 06_normalisation",
             "s2/sql/run_s2.sh : 10_catalogue → 15_hierarchie (| tee résultats)",
             "run_all.sh recrée les schémas S1 (DROP … CASCADE) ⇒ relancer S2"),
           C2 + 5, 395, W2 - 10, 90, "orc")

trf_s1 = box(T("Indicateurs &amp; anomalies S1".replace("&amp;", "&"), "04_indicateurs.sql : CA, paniers, statuts",
               "05_anomalies.sql : incohérences commandes / paiements",
               "06_normalisation.sql : exemple de passage en 3FN"),
             C4 + 5, 170, W4 - 10, 90, "trf")
trf_s2 = box(T("SQL avancé S2 (catalogue)", "12_classements : fonctions de fenêtre (classements)",
               "13_evolution : évolutions temporelles", "14_segmentation : CTE, segmentation",
               "15_hierarchie : CTE récursive sur categories"),
             C4 + 5, 280, W4 - 10, 110, "trf")

res_s1 = doc(T("Sortie psql S1", "contrôles, indicateurs et anomalies affichés", "→ SOLUTION_S1.md"),
             C5 + 5, 170, W5 - 10, 70, kind="res")
res_s2 = doc(T("s2/resultats/10…15_*.txt", "sorties psql de chaque script (tee)", "→ SOLUTION_S2.md · REFERENCE_SQL.md"),
             C5 + 5, 280, W5 - 10, 75, kind="res")

edge(s1csv, ing_imp, "data", "CSV")
edge(s1json, ing_imp, "data", "NDJSON")
edge(s2csv, ing_imp, "data", "CSV", pts=[(392, 347), (392, 250)], extra="exitX=1;exitY=0.5;entryX=0;entryY=0.8;")
edge(ing_imp, pg_rec, "data", "INSERT brut", pts=[(1000, 225)])
edge(pg_rec, ing_ctl, "data", "lecture", pts=[(1080, 255), (1080, 320)], extra="exitX=0;exitY=0.75;entryX=1;entryY=0.4;")
edge(ing_ctl, pg_rej, "rej", "lignes refusées", pts=[(1050, 340), (1050, 327)], extra="exitX=1;exitY=0.65;entryX=0;entryY=0.5;")
edge(ing_ctl, pg_nova, "data", "lignes valides typées", pts=[(1020, 360), (1020, 425)], extra="exitX=1;exitY=0.85;entryX=0;entryY=0.5;")
edge(pg_nova, trf_s1, "data", "", pts=[(1452, 410), (1452, 215)], extra="exitX=1;exitY=0.35;entryX=0;entryY=0.5;")
edge(pg_nova, trf_s2, "data", "", pts=[(1458, 440), (1458, 335)], extra="exitX=1;exitY=0.65;entryX=0;entryY=0.5;")
edge(trf_s1, res_s1, "data", "")
edge(trf_s2, res_s2, "data", "")

# ================= BRANCHE 2 =================
src_gen = doc(T("s3/generer.sql", "generate_series(1, 10 000 000)", "ventes synthétiques déterministes", "(aucune donnée externe)"),
              C1 + 5, 585, W1 - 10, 80, kind="src")
ing_gen = box(T("Génération unique (DOCKER · psql dans postgres)", "BEGIN → CREATE SCHEMA benchmark → CREATE TABLE AS",
                "→ ANALYZE → COMMIT (2e passage : échec + annulation)"),
              C2 + 5, 590, W2 - 10, 70, "ing")
trf_b = box(T("Benchmark s3/sql/run_s3.sh (LOCAL · bash → psql)", "20_contexte_volume · 21_index · 22_estimations · 23_multiplication",
              "requêtes QA_selectif · QB_large · QB_force_index",
              "EXPLAIN (ANALYZE, BUFFERS) avant / après index",
              "docker compose restart postgres (cache froid), REPS = 3"),
            C4 + 5, 570, W4 - 10, 120, "trf")
res_b = doc(T("s3/resultats/", "plans/*.txt (plans EXPLAIN complets)", "mesures.csv · 20…23_*.txt"),
            C5 + 5, 570, W5 - 10, 65, kind="res")
res_syn = box(T("s3/sql/synthese.py (LOCAL · python3 hôte)", "bibliothèque standard : csv, statistics", "→ synthese.md · SOLUTION_S3.md"),
              C5 + 5, 655, W5 - 10, 65, "trf")
edge(src_gen, ing_gen, "data", "")
edge(ing_gen, pg_bench, "data", "10 M lignes", pts=[(1000, 625)])
edge(pg_bench, trf_b, "data", "lectures / index", pts=[(1450, 630)])
edge(trf_b, res_b, "data", "", extra="exitX=1;exitY=0.27;entryX=0;entryY=0.5;")
edge(res_b, res_syn, "data", "mesures.csv")

# ================= BRANCHE 3 =================
f_api = frame(T("DOCKER · service fournisseur (profil ingestion)"), C1 - 5, 810, W1 + 10, 175, "docker")
src_api = box(T("API fournisseur simulée — ingestion/api/server.py",
                "Python 3.12 stdlib : http.server (ThreadingHTTPServer)",
                "GET /offers?page=1..6&amp;scenario=clean|atelier|panne&amp;run=".replace("&amp;", "&"),
                "GET /health · fautes déterministes : 429, 5xx, JSON invalide",
                "latence API_LATENCY_SECONDS = 0,12 s · données fictives",
                ":8080 → 127.0.0.1:18080"),
              C1 + 5, 845, W1 - 10, 130, "src")
src_cat = doc(T("Référentiel produits", "s2/donnees/products.csv (même fichier que S2)", "monté en lecture seule dans collecteur"),
              C1 + 5, 1000, W1 - 10, 60, kind="src")
src_lots = doc(T("Lots S4 de démonstration", "transformation/exemple_lots/*.jsonl", "(jour_precedent, correction_prix, defectueux)",
                 "transformation/secours/offres.jsonl"),
               C1 + 5, 1075, W1 - 10, 75, kind="src")

f_col = frame(T("DOCKER · service collecteur (profil ingestion)", "ou venv local Python 3.12 · tests : python -m unittest"),
              C2 - 5, 810, W2 + 10, 255, "docker")
ing_col = box(T("collecteur.py — collecte asynchrone", LIB("aiohttp 3.13", "asyncio", "hashlib"),
                "page 1 → total_pages, puis pages 2..N en parallèle (sémaphore)",
                "réessais : timeout, 429, 5xx, JSON — Retry-After / backoff exp.",
                "page manquante ⇒ lot en échec, rien n'est publié"),
              C2 + 5, 855, W2 - 10, 90, "ing")
ing_val = box(T("validation.py — contrat de données", "structure (7 champs, types stricts) puis règles métier :",
                "fournisseur ∈ {F01,F02,F03}, EUR, product_id ∈ catalogue, offer_id unique",
                "toutes les fautes d'une offre sont relevées"),
              C2 + 5, 953, W2 - 10, 72, "ing")
ing_log = box(T("journalisation.py — logs JSONL (logging) + Bilan (compteurs, motifs)"),
              C2 + 5, 1030, W2 - 10, 30, "ing")

f_chg = frame(T("DOCKER · service chargeur (profil transfo)", "image collecteur · entrypoint chargement_postgres.py"),
              C2 - 5, 1080, W2 + 10, 170, "docker")
ing_load = box(T("chargement_postgres.py — chargeur S4", LIB("psycopg 3.3"),
                 "UNE transaction + verrou applicatif ; empreinte SHA-256 du lot",
                 "contrôles ligne : JSON, types, EUR, date, fournisseur connu,",
                 "produit ∈ nova.products, doublon dans le lot",
                 "UPSERT (offer_id, observed_on) : insérée / mise à jour / réutilisée",
                 "erreur ⇒ ROLLBACK, lot tracé « annule » · --essai · --echouer-apres"),
               C2 + 5, 1125, W2 - 10, 118, "ing")

f_files = frame(T("LOCAL · fichiers hôte ingestion/data/", "bind mount ./ingestion → /work/ingestion"),
                FILES_X - 10, 810, FILES_W + 20, 300, "local")
sto_raw = doc(T("raw/&lt;run&gt;.jsonl".replace("&lt;", "<").replace("&gt;", ">"), "toutes les réponses reçues (même refusées)"),
              FILES_X, 855, FILES_W, 50)
sto_valid = doc(T("valid/offres.jsonl", "+ offres.manifest.json (run, SHA-256)", "publication atomique (tmp → rename)",
                  "valid/runs/<run>.jsonl (historique)"),
                FILES_X, 915, FILES_W, 75)
sto_rej = doc(T("rejected/<run>.jsonl", "offres rejetées + motifs"), FILES_X, 1000, FILES_W, 45)
sto_log = doc(T("logs/<run>.log · bilans/<run>.json", "atelier : 24 examinées · 20 valides · 4 rejets"),
              FILES_X, 1055, FILES_W, 48)

f_dbt = frame(T("DOCKER · service dbt (profil transfo)", LIB("dbt-core 1.11", "dbt-postgres 1.10", "Jinja2", "psycopg2"),
                "projet transformation/dbt monté sur /projet · profil s4/travail/profil"),
              C4 - 5, 810, W4 + 10, 440, "docker")
trf_stg = box(T("staging — vues (dbt_dev_staging)", "stg_fournisseur__offres · stg_fournisseur__fournisseurs",
                "stg_nova__products · stg_nova__categories · stg_nova__order_lines",
                "lit source('fournisseur', …) et source('nova', …) : renommage, typage"),
              C4 + 5, 870, W4 - 10, 80, "trf")
trf_int = box(T("intermediate — vues (dbt_dev_intermediate)", "int_offres__enrichies (offres × produits × fournisseurs)",
                "int_offres__derniere_observation (dernière offre par produit)",
                "int_ventes__par_produit (agrégat ventes S1/S2)"),
              C4 + 5, 965, W4 - 10, 80, "trf")
trf_mart = box(T("marts — table (dbt_dev_marts)", "mart_offres_par_produit : offres + ventes par produit"),
               C4 + 5, 1060, W4 - 10, 45, "trf")
trf_tst = box(T("Tests — dbt build (PASS = 41)", "génériques : unique, not_null, relationships, accepted_values",
                "singuliers : grain unique, sans multiplication, CA réf. S2,", "volumes, valeurs plausibles"),
              C4 + 5, 1120, W4 - 10, 70, "trf")
text('<font style="font-size:10px" color="#555">Orchestration LOCAL : transformation/run_s4.sh → docker compose run chargeur / dbt (compile, run, build)</font>',
     C4 + 5, 1198, W4 - 10, 40)

res_s4 = doc(T("transformation/resultats/01…07", "chargement &amp; rejeu, atomicité, essais, journal des lots,".replace("&amp;", "&"),
               "dbt compile/run/build, SQL compilé du mart, volumes",
               "→ SOLUTION_S4.md"),
             C5 + 5, 1060, W5 - 10, 80, kind="res")
f_mb = frame(T("DOCKER · service metabase (profil bi) — PRÉVU S6", "metabase/metabase:v0.64.8 · 127.0.0.1:13000 → 3000",
               "base applicative metabase_s6_app dans postgres", "lirait dbt_dev_marts (SQL) · déclaré dans compose.yaml,", "non exploité en S1–S5"),
             C5 - 5, 870, W5 + 10, 105, "planned")
res_mb = f_mb

edge(src_api, ing_col, "data", "pages JSON", pts=[(390, 900)], extra="exitX=1;exitY=0.4;entryX=0;entryY=0.5;")
edge(ing_col, src_api, "tech", "HTTP GET (aiohttp)<br>http://fournisseur:8080", pts=[(395, 945)], extra="exitX=0;exitY=0.85;entryX=1;entryY=0.75;")
edge(src_cat, ing_val, "tech", "référentiel", pts=[(395, 1030), (395, 990)], extra="exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
edge(ing_col, sto_raw, "data", "brut", pts=[(850, 880)], extra="exitX=1;exitY=0.3;entryX=0;entryY=0.5;")
edge(ing_col, ing_val, "data", "", extra="exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
edge(ing_val, sto_valid, "data", "valides", pts=[(855, 970), (855, 952)], extra="exitX=1;exitY=0.25;entryX=0;entryY=0.5;")
edge(ing_val, sto_rej, "rej", "rejets", pts=[(845, 1000), (845, 1022)], extra="exitX=1;exitY=0.7;entryX=0;entryY=0.5;")
edge(ing_log, sto_log, "tech", "", pts=[(858, 1044), (858, 1079)], extra="exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
edge(sto_valid, ing_load, "data", "valid/offres.jsonl (monté en lecture seule)", pts=[(1130, 952), (1130, 1137)],
     extra="exitX=1;exitY=0.5;entryX=1;entryY=0.1;", lx=0.55)
edge(src_lots, ing_load, "data", "--fichier", pts=[(390, 1112), (390, 1200)], extra="exitX=1;exitY=0.5;entryX=0;entryY=0.65;")
edge(ing_load, pg_four, "data", "UPSERT + traces de lot", pts=[(860, 1215), (1139, 1215), (1139, 880)],
     extra="exitX=1;exitY=0.77;entryX=0;entryY=0.55;", lx=-0.55)
edge(ing_load, pg_nova, "tech", "contrôle produit ∈ nova.products (SQL, TCP 5432)", pts=[(860, 1236), (1148, 1236), (1148, 460)],
     extra="exitX=1;exitY=0.95;entryX=0;entryY=0.85;", lx=-0.78)
edge(pg_four, trf_stg, "data", "", pts=[(1452, 873), (1452, 894)], extra="exitX=1;exitY=0.5;entryX=0;entryY=0.3;")
edge(pg_nova, trf_stg, "dep", "dépendance<br>branche 1 → 3", pts=[(1464, 465), (1464, 930)],
     extra="exitX=1;exitY=0.9;entryX=0;entryY=0.75;", lx=0.1)
edge(trf_stg, trf_int, "data", "ref()")
edge(trf_int, trf_mart, "data", "ref()")
edge(trf_mart, trf_tst, "tech", "tests")
edge(trf_mart, pg_dbt, "data", "", pts=[(1458, 1083), (1458, 1000)],
     extra="exitX=0;exitY=0.5;entryX=1;entryY=0.65;")
edge(trf_mart, f_mb, "tech", "", pts=[(1922, 1083), (1922, 935)], extra="exitX=1;exitY=0.5;entryX=0;entryY=0.7;")
edge(trf_tst, res_s4, "data", "preuves", extra="exitX=1;exitY=0.4;entryX=0;entryY=0.6;")

# ================= BRANCHE 4 =================
hf = cloud(T("Hugging Face Hub (Internet, HTTPS)", "dataset DinoPonjevic/NYC_TaxiData", "révision épinglée 5941adb…",
             "371 Parquet · 39,35 Go", "partition 2024/yellow/…2024-01.parquet"),
           C1, 1305, W1, 150)
src_z = doc(T("volumetrie/secours/zones.csv", "référentiel zones TLC (NYC Open Data)"), C1 + 5, 1470, W1 - 10, 50, kind="src")
src_f = doc(T("volumetrie/secours/trajets_fictifs.jsonl", "trajets synthétiques (mode --secours, publication)"),
            C1 + 5, 1530, W1 - 10, 50, kind="src")

f_vol = frame(T("DOCKER · service volumetrie (profil volumetrie)", LIB("Python 3.12", "OpenJDK 21", "datasets 4.5", "huggingface_hub 1.4",
                                                                      "pyarrow", "pyspark 4.1.1") +
                " · bind . → /work · 2 CPU / 2 Go · orchestration volumetrie/run_s5.sh"),
              C2 - 5, 1305, 1880, 335, "docker")
m1 = box(T("M1 · hf_datasets/fiche_source.py + acces.py --infos", LIB("HfApi", "HfFileSystem", "pyarrow.parquet"),
           "métadonnées du dépôt + pied de page Parquet (lecture par plages)", "aucune ligne parcourue"),
         C2 + 5, 1360, W2 - 10, 75, "ing")
m2 = box(T("M2 · streaming/extraire.py", LIB("datasets.load_dataset(streaming=True)"),
           "3 colonnes projetées, lots de 128, limite 200 000 lignes",
           "contrôle structurel · écriture tmp → rename"),
         C2 + 5, 1445, W2 - 10, 75, "ing")
m3 = box(T("M3 · streaming/controler.py", "règles Q1–Q7 : type, manquant, distance ≤ 100 mi,",
           "durée ≤ 6 h, vitesse ≤ 80 mph (1er échec = motif)", "196 326 conformes · 3 674 rejets motivés"),
         C2 + 5, 1530, W2 - 10, 75, "ing")

sto_ext = doc(T("data/extraction/trajets_extraits.jsonl", "200 000 enregistrements bruts"), FILES_X, 1360, FILES_W + 100, 45)
sto_spk = doc(T("data/spark/trajets_controles.jsonl", "entrée Spark (lignes conformes)"), FILES_X, 1415, FILES_W + 100, 45)
sto_rjs = doc(T("data/spark/trajets_rejetes.jsonl", "rejets + motif + ligne_source"), FILES_X, 1470, FILES_W + 100, 45)
sto_bil = doc(T("resultats/01_fiche_source · 02_bilan_extraction", "04_bilan_qualite (.json) — compteurs, empreintes"),
              FILES_X, 1525, FILES_W + 100, 50, kind="res")

spark = box(T("M4 · spark/pipeline.py", LIB("pyspark.sql : SparkSession local[2]", "functions", "types"),
              "lecture JSONL + CSV, schéma explicite, filtre qualité",
              "variable calculée : vitesse moyenne",
              "contrôle unicité zone_id, anti-jointure (non appariés)",
              "jointure gauche broadcast sans multiplication",
              "agrégats par zone / arrondissement · explain()",
              "verifier.py : diagnostic Spark local"),
            C4 + 5, 1360, W4 - 10, 150, "trf")

parq = doc(T("data/sorties/<run>/", "par_arrondissement/ · par_zone/ (Parquet)", "relus et recomptés (= effectif joint)",
             "resultats/05_spark_pipeline.txt"),
           C5 + 5, 1355, W5 - 10, 80, kind="res")
pub = box(T("M5 · publication/preparer.py", LIB("pyarrow"), "README.md (Dataset Card) + trajets_synthetiques.parquet",
            "v1 → v2 documentée · seules données autorisées"),
          C5 + 5, 1450, W5 - 10, 80, "res")
hub = cloud(T("Hugging Face Hub", "dépôt dataset du groupe (v1, v2)", "hf auth login + upload manuel"), C5 + 20, 1640, W5 - 40, 85)

edge(hf, m1, "tech", "API métadonnées", pts=[(390, 1340), (390, 1395)], extra="exitX=0.85;exitY=0.25;entryX=0;entryY=0.5;")
edge(hf, m2, "data", "streaming HTTPS", extra="exitX=0.95;exitY=0.65;entryX=0;entryY=0.5;")
edge(m1, sto_bil, "data", "", pts=[(860, 1385), (860, 1560)], extra="exitX=1;exitY=0.35;entryX=0;entryY=0.7;")
edge(m2, sto_ext, "data", "JSONL", pts=[(850, 1470), (850, 1382)], extra="exitX=1;exitY=0.35;entryX=0;entryY=0.5;")
edge(sto_ext, m3, "data", "", pts=[(1235, 1382), (1235, 1620), (620, 1620)], extra="exitX=1;exitY=0.5;entryX=0.5;entryY=1;")
edge(m3, sto_spk, "data", "conformes", pts=[(855, 1555), (855, 1437)], extra="exitX=1;exitY=0.3;entryX=0;entryY=0.5;")
edge(m3, sto_rjs, "rej", "rejets", pts=[(845, 1575), (845, 1492)], extra="exitX=1;exitY=0.6;entryX=0;entryY=0.5;")
edge(sto_spk, spark, "data", "", extra="exitX=1;exitY=0.5;entryX=0;entryY=0.5;", pts=[(1460, 1437), (1460, 1430)])
edge(src_z, spark, "data", "zones.csv", pts=[(380, 1495), (380, 1630), (1455, 1630), (1455, 1480)],
     extra="exitX=1;exitY=0.5;entryX=0;entryY=0.8;")
edge(spark, parq, "data", "Parquet", extra="exitX=1;exitY=0.3;entryX=0;entryY=0.5;", pts=[(1920, 1405), (1920, 1395)])
edge(src_f, pub, "data", "synthétique + zones", pts=[(395, 1555), (395, 1660), (1925, 1660), (1925, 1505)],
     extra="exitX=1;exitY=0.5;entryX=0;entryY=0.7;")
edge(pub, hub, "data", "upload v1 / v2", extra="exitX=0.5;exitY=1;entryX=0.5;entryY=0;")

# ================= INFRASTRUCTURE =================
IY = 1760
frame(T("INFRASTRUCTURE D'EXÉCUTION — poste local macOS + Docker Desktop",
        "projet Compose <b>novamarket-s1</b> : compose.yaml (racine) → include novamarket/compose.yaml · réseau bridge 10.244.172.0/24 (DNS interne : postgres, fournisseur) · ports publiés sur 127.0.0.1 uniquement · secrets saisis en session (read -rs PGPASSWORD), jamais commités"),
      20, IY, 2630, 300, "local")
CW, CH, GAP, CX0, CY = 268, 175, 12, 35, IY + 60
cards = [
    ("fournisseur", "profil ingestion", ["build ingestion/api/Dockerfile", "cible fournisseur (python:3.12-slim)", "127.0.0.1:18080 → 8080", "128 Mo · user 65534 (non root)", "healthcheck GET /health"]),
    ("collecteur", "profil ingestion", ["même Dockerfile, cible collecteur", "pip -r requirements-v3.txt (aiohttp, psycopg)", "NOVAMARKET_API_URL=http://fournisseur:8080", "depends_on fournisseur (healthy)", "bind ./ingestion, ./s2/donnees:ro · 256 Mo"]),
    ("chargeur", "profil transfo", ["image cible collecteur", "entrypoint chargement_postgres.py", "DSN host=postgres port=5432", "PGPASSWORD passé depuis la session", "bind ./transformation, ./ingestion/data:ro"]),
    ("postgres", "toujours actif", ["postgres:17.12-bookworm (digest épinglé)", "127.0.0.1:15432 → 5432", "volume postgres_data · ./s1:/s1:ro", "2 CPU / 2 Go", "healthcheck pg_isready"]),
    ("dbt", "profil transfo", ["build s4/ (python:3.12-slim + git)", "dbt-core 1.11.17 · dbt-postgres 1.10.2", "bind ./transformation/dbt → /projet", "./s4/travail → /work (profil dbt)", "1 Go · 2 CPU"]),
    ("metabase", "profil bi · prévu S6", ["metabase/metabase:v0.64.8", "127.0.0.1:13000 → 3000", "MB_DB_HOST=postgres", "base metabase_s6_app", "2 Go · JVM -Xmx1g"]),
    ("volumetrie", "profil volumetrie", ["build volumetrie/ (python:3.12-slim-trixie)", "+ OpenJDK 21 (JRE headless)", "bind . → /work · HF_HUB_DISABLE_XET=1", "UID/GID du poste (entree.sh)", "2 Go · 2 CPU · sortie Internet (HF)"]),
    ("Hôte (hors conteneur)", "LOCAL", ["bash : run_all.sh, run_s2.sh, run_s3.sh,", "run_s4.sh, run_s5.sh (docker compose …)", "python3 système : s3/sql/synthese.py", "pas de Java ni de Python 3.12 requis", "GitHub Codespaces possible (.devcontainer)"]),
]
card_ids = {}
for i, (name, prof, lines) in enumerate(cards):
    x = CX0 + i * (CW + GAP)
    kind = "ext" if name.startswith("Hôte") else ("ext" if name == "metabase" else "res")
    extra = "dashed=1;" if name == "metabase" else ""
    lab = T(name, *lines, tag=("DOCKER · " + prof) if not name.startswith("Hôte") else "LOCAL · poste macOS")
    card_ids[name] = box(lab, x, CY, CW, CH, kind, extra=extra + ("fillColor=#eef5ff;strokeColor=#1f6feb;" if kind == "res" else ""))

def cx(i, f):
    return CX0 + i * (CW + GAP) + CW * f
YB = CY + CH
edge(card_ids["collecteur"], card_ids["fournisseur"], "tech", "HTTP GET :8080 (aiohttp)",
     pts=[(cx(1, 0.3), YB + 22), (cx(0, 0.7), YB + 22)], extra="exitX=0.3;exitY=1;entryX=0.7;entryY=1;")
edge(card_ids["chargeur"], card_ids["postgres"], "tech", "TCP 5432 · psycopg 3",
     pts=[(cx(2, 0.5), YB + 22), (cx(3, 0.25), YB + 22)], extra="exitX=0.5;exitY=1;entryX=0.25;entryY=1;")
edge(card_ids["dbt"], card_ids["postgres"], "tech", "TCP 5432 · psycopg2",
     pts=[(cx(4, 0.5), YB + 22), (cx(3, 0.75), YB + 22)], extra="exitX=0.5;exitY=1;entryX=0.75;entryY=1;")
edge(card_ids["metabase"], card_ids["postgres"], "tech", "TCP 5432 (S6)",
     pts=[(cx(5, 0.5), YB + 48), (cx(3, 0.5), YB + 48)], extra="exitX=0.5;exitY=1;entryX=0.5;entryY=1;")
inet = cloud(T("Internet", "huggingface.co (HTTPS 443)", "API Hub · fichiers Parquet", "upload des révisions v1/v2"),
             LEG + 10, CY + 10, 300, 150)
edge(card_ids["volumetrie"], inet, "tech", "HTTPS (requêtes par plages, streaming)",
     pts=[(cx(6, 0.5), CY - 38), (LEG + 160, CY - 38)], extra="exitX=0.5;exitY=0;entryX=0.5;entryY=0;")
edge(card_ids["Hôte (hors conteneur)"], card_ids["postgres"], "tech", "docker compose exec psql",
     pts=[(CX0 + 7 * (CW + GAP) + CW / 2, CY - 18), (CX0 + 3 * (CW + GAP) + CW / 2, CY - 18)],
     extra="exitX=0.5;exitY=0;entryX=0.5;entryY=0;")

# ================= LÉGENDE =================
LY = 110
frame("<b>LÉGENDE</b>", LEG, LY, 320, 1050, "local")
y = LY + 40
for lab, kind in [("Source de données", "src"), ("Ingestion / validation", "ing"), ("Stockage (fichier / schéma)", "sto"),
                  ("Traitement / transformation", "trf"), ("Restitution / livrable", "res"), ("Service externe / infra", "ext")]:
    box(lab, LEG + 15, y, 290, 30, kind, extra="verticalAlign=middle;")
    y += 40
cyl("Table / schéma PostgreSQL", LEG + 15, y, 140, 45)
doc("Fichier (JSONL, CSV, Parquet, txt)", LEG + 165, y, 140, 45)
y += 60
cloud("Service Internet", LEG + 15, y, 140, 55)
box("Orchestration (script bash)", LEG + 165, y + 10, 140, 35, "orc", extra="verticalAlign=middle;")
y += 75
frame(T("DOCKER · service", "conteneur Compose (profil)"), LEG + 15, y, 290, 45, "docker")
y += 55
frame(T("LOCAL", "poste / fichiers de l'hôte"), LEG + 15, y, 290, 45, "local")
y += 55
frame(T("PRÉVU (non exploité)", "déclaré, hors périmètre S1–S5"), LEG + 15, y, 290, 45, "planned")
y += 70
for lab, kind in [("Flux de données", "data"), ("Flux de rejets / anomalies", "rej"),
                  ("Dépendance de données inter-branches", "dep"),
                  ("Relation technique : appel HTTP, connexion SQL, lecture de référentiel, exec", "tech")]:
    a = vertex("", LEG + 15, y + 8, 2, 2, "text;strokeColor=none;fillColor=none;")
    b = vertex("", LEG + 95, y + 8, 2, 2, "text;strokeColor=none;fillColor=none;")
    edge(a, b, kind, "")
    text(lab, LEG + 105, y - 4, 205, 40)
    y += 45
text('<i><font color="#7a3e9d">texte violet italique</font></i> = bibliothèques / packages Python principaux', LEG + 15, y, 290, 35)
y += 45
text('<b>Branches indépendantes</b><br><font style="font-size:10px">• Branche 2 (benchmark) et branche 4 (S5) ne partagent aucune donnée avec les autres : exécutables seules.<br>'
     '• Branche 3 : la collecte (API → fichiers) tourne sans PostgreSQL ; seuls le chargeur et dbt exigent la branche 1 (nova.*).<br>'
     '• Branche 1 : S2 après S1 (run_all.sh recrée les schémas).</font>',
     LEG + 15, y, 290, 140)
y += 150
text('<b>Ordre de rejeu (README)</b><br><font style="font-size:10px">1. docker compose up -d --wait postgres<br>2. run_all.sh → run_s2.sh<br>3. generer.sql → run_s3.sh<br>'
     '4. --profile ingestion : collecteur --scenario atelier<br>5. run_s4.sh --reinitialiser<br>6. --profile volumetrie : run_s5.sh</font>',
     LEG + 15, y, 290, 120)

# ---------- assemblage ----------
model = ('<mxGraphModel dx="2400" dy="1600" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
         'page="1" pageScale="1" pageWidth="2700" pageHeight="2100" math="0" shadow="0" background="#ffffff">'
         '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel>")
xml = ('<mxfile host="app.diagrams.net" agent="NovaMarket generator" version="24.0.0">'
       '<diagram id="novamarket-archi" name="Architecture &amp; flux NovaMarket">' + model + "</diagram></mxfile>")
with open(OUT, "w", encoding="utf-8") as f:
    f.write(xml)

# URL #R : encodeURIComponent → deflate brut → base64
enc = urllib.parse.quote(xml, safe="-_.!~*'()")
co = zlib.compressobj(9, zlib.DEFLATED, -15)
comp = co.compress(enc.encode("utf-8")) + co.flush()
b64 = base64.b64encode(comp).decode()
with open(URL_OUT, "w") as f:
    f.write("https://app.diagrams.net/#R" + urllib.parse.quote(b64, safe=""))
print(len(cells), "cellules ·", len(xml), "octets XML ·", len(b64), "octets compressés")
