"""Schéma simplifié NovaMarket (version corrigée) au format .drawio.

Usage : python3 devoir1/generer_schema_simple.py devoir1/NovaMarket_schema_simple.drawio
"""
import html
import sys

cells = []
_n = [0]


def nid():
    _n[0] += 1
    return f"s{_n[0]}"


def esc(s):
    return html.escape(s, quote=True)


def L(title, *lines):
    s = f"<b>{title}</b>"
    if lines:
        s += "<br>" + "<br>".join(lines)
    return s


FONT = "fontFamily=Helvetica;fontSize=13;fontColor=#1a1a1a;whiteSpace=wrap;html=1;"
STEP = "rounded=1;arcSize=12;strokeWidth=2;strokeColor=#1a1a1a;fillColor=#ffffff;" + FONT
DOC = "shape=document;size=0.18;boundedLbl=1;strokeWidth=2;strokeColor=#1a1a1a;fillColor=#ffffff;" + FONT
CYL = "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;strokeWidth=2;strokeColor=#1a1a1a;fillColor=#ffffff;" + FONT
RED = "strokeColor=#c0392b;fillColor=#fdecea;"
GREEN = "fillColor=#5cb85c;strokeColor=#3d8b3d;"
NET = "dashed=1;dashPattern=6 4;"


def v(label, x, y, w, h, style):
    cid = nid()
    cells.append(f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


E_DATA = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#1a1a1a;strokeWidth=2;endArrow=block;endFill=1;fontSize=12;fontColor=#1a1a1a;labelBackgroundColor=#ffffff;"
E_REJ = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#c0392b;strokeWidth=2;endArrow=block;endFill=1;fontSize=12;fontColor=#c0392b;labelBackgroundColor=#ffffff;"
E_DBT = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#777777;strokeWidth=2;dashed=1;dashPattern=6 4;endArrow=open;endFill=0;fontSize=12;labelBackgroundColor=#ffffff;"
E_DEP = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#1f6feb;strokeWidth=2;dashed=1;dashPattern=2 3;endArrow=block;endFill=1;fontSize=12;fontColor=#1f4e9e;labelBackgroundColor=#ffffff;"


def e(src, tgt, style, label="", pts=None, extra=""):
    cid = nid()
    geo = '<mxGeometry relative="1" as="geometry">'
    if pts:
        geo += '<Array as="points">' + "".join(f'<mxPoint x="{a}" y="{b}"/>' for a, b in pts) + "</Array>"
    geo += "</mxGeometry>"
    cells.append(f'<mxCell id="{cid}" value="{esc(label)}" style="{style}{extra}" edge="1" parent="1" '
                 f'source="{src}" target="{tgt}">{geo}</mxCell>')


def frame(label, x, y, w, h):
    return v(label, x, y, w, h, "rounded=0;dashed=1;dashPattern=4 4;strokeColor=#555555;fillColor=none;"
             "verticalAlign=top;align=left;spacingLeft=12;spacingTop=6;fontStyle=1;" + FONT.replace("fontSize=13", "fontSize=16"))


def text(label, x, y, w, h, size=13):
    return v(label, x, y, w, h, "text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;" +
             FONT.replace("fontSize=13", f"fontSize={size}"))


text("<b>NovaMarket : schéma du projet (S1 à S5)</b>", 15, 8, 900, 35, 22)
text("Groupe : ______________________", 1500, 14, 480, 30, 14)

# ---------- S3 ingestion + S4 chargement (offres fournisseurs) ----------
api = v(L("API Fournisseur", "donne les offres, port 8080", "(Docker · http.server)"), 10, 185, 245, 95, STEP)
col = v(L("Collecteur", "récupère les offres", "(Docker · aiohttp)"), 355, 185, 235, 95, STEP)
prod = v(L("Liste des produits", "(fichier S2)"), 685, 55, 235, 75, DOC)
val = v(L("Validation", "vérifie chaque offre", "(Docker · validation.py)"), 685, 185, 235, 95, STEP)
ref1 = v(L("Offres refusées", "(fichier rejected/)"), 685, 335, 235, 75, DOC + RED)
okf = v(L("Fichier des", "offres valides"), 1015, 185, 225, 90, DOC)
chg = v(L("Chargeur", "envoie dans la base", "(Docker · psycopg 3)"), 1335, 185, 295, 95, STEP)
vchk = v(L("Vérification", "avant l'envoi (tout ou rien)"), 1335, 355, 295, 85, STEP)
ref2 = v(L("Lignes refusées", "(table lot_lignes)"), 1725, 355, 245, 85, CYL + RED)
tf = v(L("Table fournisseur", "(PostgreSQL)"), 1360, 565, 245, 100, CYL)

e(api, col, E_DATA, "HTTP")
e(col, val, E_DATA)
e(prod, val, E_DATA)
e(val, ref1, E_REJ, "refusé")
e(val, okf, E_DATA, "OK")
e(okf, chg, E_DATA, "lit")
e(chg, vchk, E_DATA)
e(vchk, ref2, E_REJ, "refusé")
e(vchk, tf, E_DATA, "ajoute, met à jour<br>ou réutilise (sans doublon)")

# ---------- S1 / S2 / S3 benchmark (PostgreSQL) ----------
f1 = v(L("Fichiers S1", "clients, commandes,", "paiements"), 10, 565, 245, 105, DOC)
f2 = v(L("Fichiers S2", "catégories, produits"), 10, 745, 245, 80, DOC)
psql = v(L("psql", "lance le SQL", "(Docker, dans le", "conteneur postgres)"), 368, 560, 220, 130, STEP)
rec = v(L("Réception", "données brutes", "(PostgreSQL)"), 698, 570, 245, 100, CYL)
ver = v(L("Vérifications", "types, clés, doublons"), 698, 745, 245, 90, STEP)
ref3 = v(L("Lignes refusées", "(table rejets.journal)"), 1030, 745, 230, 90, CYL + RED)
tp = v(L("Tables propres", "(PostgreSQL)"), 698, 920, 245, 100, CYL)
bench = v(L("Benchmark (S3)", "10 millions de lignes", "générées, indépendant", "(PostgreSQL)"), 355, 1085, 245, 115, CYL)
res = v(L("Résultats", "indicateurs, analyses,", "temps mesurés (txt, csv)"), 698, 1090, 270, 105,
        "rounded=1;arcSize=12;strokeWidth=2;" + GREEN + FONT)

e(f1, psql, E_DATA, "import")
e(f2, psql, E_DATA, "import", pts=[(320, 785), (320, 660)], extra="entryX=0;entryY=0.77;")
e(psql, rec, E_DATA, "charge")
e(rec, ver, E_DATA)
e(ver, ref3, E_REJ, "refusé")
e(ver, tp, E_DATA, "OK")
e(psql, bench, E_DATA, "génère")
e(tp, res, E_DATA, "requêtes SQL")
e(bench, res, E_DATA, "mesures")

# dépendance : le chargeur contrôle les produits dans les tables propres
e(tp, vchk, E_DEP, "le produit existe ?", pts=[(1295, 945), (1295, 420)], extra="exitX=1;exitY=0.25;entryX=0;entryY=0.75;")

# ---------- dbt (S4) ----------
dbt = v(L("dbt", "construit et teste", "(Docker · dbt-postgres)", "41 tests OK"), 1700, 700, 270, 115, STEP)
stg = v(L("dbt staging", "données nettoyées"), 1360, 920, 245, 100, CYL)
itm = v(L("dbt intermediate", "offres enrichies,", "ventes par produit"), 1700, 920, 270, 100, CYL)
mrt = v(L("dbt marts", "offres + ventes", "par produit"), 1700, 1090, 270, 105, CYL)

e(tp, stg, E_DATA, "catalogue + commandes", extra="exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e(tf, stg, E_DATA)
e(stg, itm, E_DATA, "regroupe")
e(itm, mrt, E_DATA, "résume")
e(dbt, stg, E_DBT, pts=[(1555, 757)], extra="exitX=0;exitY=0.5;entryX=0.8;entryY=0;")
e(dbt, itm, E_DBT)
e(dbt, mrt, E_DBT, pts=[(2000, 757), (2000, 1142)], extra="exitX=1;exitY=0.5;entryX=1;entryY=0.5;")

# ---------- S5 ----------
frame("S5 : partie à part (gros fichiers, pas de PostgreSQL) · tout tourne dans le conteneur Docker volumetrie (Python 3.12 + Java 21)",
      0, 1260, 2010, 470)
hf = v(L("Hugging Face", "données des taxis", "(Internet)"), 35, 1330, 260, 105, CYL + NET)
lec = v(L("Lecture petit à petit", "200 000 lignes", "(datasets)"), 380, 1335, 245, 100, STEP)
vt = v(L("Vérification", "des trajets", "(règles Q1 à Q7)"), 710, 1335, 245, 100, STEP)
spk = v(L("Spark", "calcule par zone", "(pyspark)"), 1040, 1335, 270, 100, STEP)
pq = v(L("Fichiers résultats", "Parquet, restent sur le PC", "(non publiés)"), 1395, 1335, 260, 95, DOC)
rt = v(L("Trajets refusés", "+ motif"), 710, 1485, 245, 70, DOC + RED)
zn = v(L("Liste des zones", "(fichier TLC)"), 1040, 1485, 270, 70, DOC)
fic = v(L("Trajets fictifs", "(fichier fourni)"), 1040, 1615, 270, 70, DOC)
prep = v(L("Préparation", "jeu fictif + fiche explicative", "(pyarrow)"), 1395, 1525, 260, 100, STEP)
hub = v(L("Hugging Face", "mon dépôt v1, v2", "(Internet)"), 1775, 1525, 205, 100, CYL + NET)

e(hf, lec, E_DATA, "HTTPS")
e(lec, vt, E_DATA)
e(vt, spk, E_DATA, "OK")
e(vt, rt, E_REJ, "refusé")
e(zn, spk, E_DATA)
e(spk, pq, E_DATA)
e(zn, prep, E_DATA, extra="exitX=1;exitY=0.5;entryX=0;entryY=0.3;")
e(fic, prep, E_DATA, extra="exitX=1;exitY=0.5;entryX=0;entryY=0.8;")
e(prep, hub, E_DATA, "publie<br>(huggingface_hub)")
text('<font color="#555555"><i>Les vraies données taxi ne sont pas republiées (licence inconnue) : seul le jeu fictif part sur le Hub.</i></font>',
     20, 1690, 900, 30, 12)

# ---------- Infrastructure ----------
frame("Où ça tourne : Docker Compose sur mon Mac (projet novamarket-s1, un réseau Docker commun)", 0, 1760, 2010, 185)
INF = "rounded=1;arcSize=8;strokeWidth=1.5;strokeColor=#1f6feb;fillColor=#eef5ff;align=left;verticalAlign=top;spacingLeft=8;spacingTop=4;" + FONT.replace("fontSize=13", "fontSize=12")
boxes = [
    L("postgres", "PostgreSQL 17", "port 15432 → 5432", "volume postgres_data", "psql : docker compose exec"),
    L("fournisseur", "l'API (Python 3.12)", "port 18080 → 8080"),
    L("collecteur", "aiohttp", "appelle http://fournisseur:8080", "écrit dans ingestion/data/"),
    L("chargeur", "psycopg 3", "se connecte à postgres:5432"),
    L("dbt", "dbt-core + dbt-postgres", "se connecte à postgres:5432"),
    L("volumetrie", "datasets · pyspark · pyarrow", "huggingface_hub", "sortie Internet (HTTPS)"),
]
for i, b in enumerate(boxes):
    v(b, 20 + i * 330, 1805, 310, 120, INF)

# ---------- Légende ----------
frame("Légende", 0, 1975, 2010, 175)


def leg_edge(style, y, label):
    a = v("", 30, y, 2, 2, "text;strokeColor=none;fillColor=none;")
    b = v("", 105, y, 2, 2, "text;strokeColor=none;fillColor=none;")
    e(a, b, style)
    text(label, 115, y - 11, 420, 25)


leg_edge(E_DATA, 2025, "les données passent par là")
leg_edge(E_REJ, 2055, "les données refusées partent là")
leg_edge(E_DBT, 2085, "dbt fabrique ces tables")
leg_edge(E_DEP, 2115, "le chargeur vérifie dans les tables propres")
text("<b>Où ça tourne ?</b><br>(Docker) = dans un conteneur<br>(PostgreSQL) = table de la base,<br>dans le conteneur postgres<br>(Internet) = sur Hugging Face",
     560, 2015, 330, 120)
v("<b>une étape</b>", 930, 2015, 160, 45, STEP)
v("<b>un fichier</b>", 930, 2080, 160, 50, DOC)
v("<b>une table</b>", 1130, 2010, 160, 55, CYL)
v("<b>rouge = refusé</b>", 1130, 2080, 160, 45, STEP + RED)
v("<b>vert = résultat final</b>", 1330, 2015, 210, 45, "rounded=1;arcSize=12;strokeWidth=2;" + GREEN + FONT)
v("<b>en pointillé = Internet</b>", 1330, 2075, 210, 55, CYL + NET)

model = ('<mxGraphModel dx="2000" dy="2200" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
         'page="1" pageScale="1" pageWidth="2030" pageHeight="2170" math="0" shadow="0" background="#ffffff">'
         '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel>")
xml = ('<mxfile host="app.diagrams.net" version="24.0.0"><diagram id="novamarket-simple" name="Schéma NovaMarket">'
       + model + "</diagram></mxfile>")
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(xml)
print(len(cells), "cellules")
