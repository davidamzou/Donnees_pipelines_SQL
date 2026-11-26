"""M3 · Contrôle qualité de l'extraction et préparation de l'entrée Spark.

Lit un JSONL ligne à ligne (aucun chargement intégral), vérifie types, valeurs
manquantes et cohérence distance/durée, puis écrit :
  - l'entrée Spark (lignes conformes, distance arrondie au centième de mile) ;
  - les rejets, chacun avec son motif (traçabilité de la sélection) ;
  - un bilan JSON avant/après (compteurs, motifs, statistiques, empreintes).

Règles, évaluées dans l'ordre ; le premier échec donne le motif du rejet :
  Q1 type_invalide       Start_Zone et Trip_Duration entiers, Trip_Distance numérique fini
  Q2 valeur_manquante    aucun des trois champs nul ou absent
  Q3 distance_non_positive Trip_Distance > 0 (0 ou négatif : course annulée ou compteur faux)
  Q4 distance_aberrante  Trip_Distance <= 100 miles (au-delà : hors périmètre urbain)
  Q5 duree_non_positive  Trip_Duration > 0 s (durées négatives : horodatages inversés)
  Q6 duree_aberrante     Trip_Duration <= 6 h = 21 600 s (au-delà : compteur non clôturé)
  Q7 vitesse_aberrante   vitesse moyenne <= 80 mph (distance incohérente avec la durée)
Les zones ne sont PAS filtrées ici : leur appariement est contrôlé par la jointure
Spark (M4), qui doit pouvoir détecter les codes inconnus.

Provenance : chaque ligne garde `ligne_source`, son rang dans le flux de la
partition (ou son numéro de ligne si le fichier d'entrée n'en a pas, cas du secours).

Usage (depuis novamarket/) : python volumetrie/streaming/controler.py
"""
import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DISTANCE_MAX_MILES = 100
DUREE_MAX_SECONDES = 6 * 3600
VITESSE_MAX_MPH = 80
CHAMPS = ("Start_Zone", "Trip_Distance", "Trip_Duration")


def est_entier(v):
    return isinstance(v, int) and not isinstance(v, bool)


def motif_rejet(enr):
    if any(enr.get(c) is None for c in CHAMPS):
        return "valeur_manquante"
    zone, distance, duree = (enr[c] for c in CHAMPS)
    if not (est_entier(zone) and est_entier(duree)) or isinstance(distance, bool) \
            or not isinstance(distance, (int, float)) or not math.isfinite(distance):
        return "type_invalide"
    if distance <= 0:
        return "distance_non_positive"
    if distance > DISTANCE_MAX_MILES:
        return "distance_aberrante"
    if duree <= 0:
        return "duree_non_positive"
    if duree > DUREE_MAX_SECONDES:
        return "duree_aberrante"
    if distance / (duree / 3600) > VITESSE_MAX_MPH:
        return "vitesse_aberrante"
    return None


class Stats:
    """Statistiques descriptives calculées en un passage (min, max, moyenne)."""

    def __init__(self):
        self.n, self.somme, self.min, self.max = 0, 0.0, math.inf, -math.inf

    def ajouter(self, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            self.n += 1
            self.somme += v
            self.min, self.max = min(self.min, v), max(self.max, v)

    def resume(self):
        if not self.n:
            return None
        return {"n": self.n, "min": round(self.min, 2), "max": round(self.max, 2),
                "moyenne": round(self.somme / self.n, 3)}


def sha256(chemin):
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def relatif(chemin):
    try:
        return str(chemin.resolve().relative_to(RACINE.parent))
    except ValueError:
        return str(chemin)


def controler(entree, sortie, rejets, bilan_chemin):
    sortie.parent.mkdir(parents=True, exist_ok=True)
    rejets.parent.mkdir(parents=True, exist_ok=True)
    motifs = Counter()
    avant = {c: Stats() for c in CHAMPS}
    apres = {c: Stats() for c in CHAMPS}
    zones_avant, zones_apres = set(), set()
    lues = conformes = illisibles = 0
    with entree.open(encoding="utf-8") as src, sortie.open("w", encoding="utf-8") as ok, \
            rejets.open("w", encoding="utf-8") as ko:
        for numero, brut in enumerate(src):
            if not brut.strip():
                continue
            lues += 1
            try:
                enr = json.loads(brut)
            except json.JSONDecodeError:
                illisibles += 1
                motifs["json_illisible"] += 1
                ko.write(json.dumps({"ligne_source": numero, "motif": "json_illisible"}) + "\n")
                continue
            enr.setdefault("ligne_source", numero)
            for c in CHAMPS:
                avant[c].ajouter(enr.get(c))
            zones_avant.add(enr.get("Start_Zone"))
            motif = motif_rejet(enr)
            if motif:
                motifs[motif] += 1
                ko.write(json.dumps({"motif": motif, **enr}, separators=(",", ":")) + "\n")
                continue
            conformes += 1
            propre = {"ligne_source": enr["ligne_source"], "Start_Zone": enr["Start_Zone"],
                      "Trip_Distance": round(float(enr["Trip_Distance"]), 2),
                      "Trip_Duration": enr["Trip_Duration"]}
            for c in CHAMPS:
                apres[c].ajouter(propre[c])
            zones_apres.add(propre["Start_Zone"])
            ok.write(json.dumps(propre, separators=(",", ":")) + "\n")

    rejetees = sum(motifs.values())
    assert lues == conformes + rejetees
    bilan = {
        "etape": "M3_controle_qualite",
        "horodatage_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entree": relatif(entree), "sha256_entree": sha256(entree),
        "sortie_spark": relatif(sortie), "sha256_sortie": sha256(sortie),
        "rejets": relatif(rejets),
        "regles": {"distance_max_miles": DISTANCE_MAX_MILES, "duree_max_secondes": DUREE_MAX_SECONDES,
                   "vitesse_max_mph": VITESSE_MAX_MPH, "arrondi_distance": 2},
        "lues": lues, "conformes": conformes, "rejetees": rejetees,
        "taux_rejet_pct": round(100 * rejetees / lues, 3) if lues else None,
        "motifs_rejet": dict(motifs.most_common()),
        "statistiques_avant": {c: s.resume() for c, s in avant.items()},
        "statistiques_apres": {c: s.resume() for c, s in apres.items()},
        "zones_distinctes_avant": len(zones_avant), "zones_distinctes_apres": len(zones_apres),
    }
    bilan_chemin.parent.mkdir(parents=True, exist_ok=True)
    bilan_chemin.write_text(json.dumps(bilan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: bilan[k] for k in ("lues", "conformes", "rejetees", "taux_rejet_pct", "motifs_rejet")},
                     ensure_ascii=False))
    return bilan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entree", type=Path, default=RACINE / "data" / "extraction" / "trajets_extraits.jsonl")
    parser.add_argument("--sortie", type=Path, default=RACINE / "data" / "spark" / "trajets_controles.jsonl")
    parser.add_argument("--rejets", type=Path, default=RACINE / "data" / "spark" / "trajets_rejetes.jsonl")
    parser.add_argument("--bilan", type=Path, default=RACINE / "resultats" / "04_bilan_qualite.json")
    a = parser.parse_args()
    controler(a.entree, a.sortie, a.rejets, a.bilan)
