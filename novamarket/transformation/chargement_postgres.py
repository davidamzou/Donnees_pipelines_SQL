"""Chargeur S4 : offres fournisseurs validées (JSONL S3) -> PostgreSQL.

Depuis novamarket/, avec le venv S3 et NOVAMARKET_DSN défini (mot de passe
par PGPASSFILE ou PGPASSWORD, jamais dans le code) :

    python transformation/chargement_postgres.py
    python transformation/chargement_postgres.py --fichier transformation/secours/offres.jsonl
    python transformation/chargement_postgres.py --essai          # exécute puis annule
    python transformation/chargement_postgres.py --echouer-apres 5  # panne simulée

Sans Python 3.12 en local : `docker compose --profile transfo run --rm chargeur [options]`.

Déroulé, dans UNE transaction :
1. schéma fournisseur (rejouable) et verrou applicatif contre deux chargements simultanés ;
2. ouverture du lot (fichier, SHA-256, run S3 d'après le manifeste) ;
3. contrôle de chaque ligne : JSON, champs, types, devise, unités, date,
   produit présent dans nova.products, fournisseur connu, doublon dans le lot ;
4. UPSERT sur (offer_id, observed_on) : insérée, mise à jour si le contenu
   diffère, réutilisée si elle est déjà présente à l'identique ;
5. trace de chaque ligne et compteurs du lot, puis COMMIT.

Toute erreur annule l'ensemble (aucune écriture partielle) ; le lot est alors
enregistré à part avec le statut `annule` et le message d'erreur.
Codes de sortie : 0 lot validé (ou essai), 1 lot annulé, 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

DOSSIER_TRANSFO = Path(__file__).resolve().parent
DOSSIER_NOVAMARKET = DOSSIER_TRANSFO.parent
ENTREE_S3 = DOSSIER_NOVAMARKET / "ingestion" / "data" / "valid" / "offres.jsonl"
ENTREE_SECOURS = DOSSIER_TRANSFO / "secours" / "offres.jsonl"
SCHEMA_SQL = DOSSIER_TRANSFO / "sql" / "schema_fournisseur.sql"
VERROU = 4_240_001  # identifiant du verrou consultatif « chargement fournisseur »

CHAMPS = ("offer_id", "supplier_id", "product_id", "price_cents",
          "currency", "available_units", "observed_on")
_IDENTIFIANT = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DATE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")

UPSERT = """
INSERT INTO fournisseur.offres AS o
    (offer_id, observed_on, supplier_id, product_id, price_cents, currency,
     available_units, lot_insertion, lot_maj)
VALUES (%(offer_id)s, %(observed_on)s, %(supplier_id)s, %(product_id)s, %(price_cents)s,
        %(currency)s, %(available_units)s, %(lot)s, %(lot)s)
ON CONFLICT (offer_id, observed_on) DO UPDATE
SET supplier_id = excluded.supplier_id, product_id = excluded.product_id,
    price_cents = excluded.price_cents, currency = excluded.currency,
    available_units = excluded.available_units,
    lot_maj = excluded.lot_maj, maj_le = clock_timestamp()
WHERE (o.supplier_id, o.product_id, o.price_cents, o.currency, o.available_units)
      IS DISTINCT FROM
      (excluded.supplier_id, excluded.product_id, excluded.price_cents,
       excluded.currency, excluded.available_units)
RETURNING (xmax = 0) AS inseree
"""


class PanneSimulee(RuntimeError):
    pass


def est_entier(valeur) -> bool:
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def controler(objet, produits: set[int], fournisseurs: set[str], aujourd_hui: date):
    """Retourne (offre typée, []) si conforme, sinon (None, motifs)."""
    if not isinstance(objet, dict):
        return None, ["structure:objet_attendu"]
    motifs = [f"champ_manquant:{c}" for c in CHAMPS if objet.get(c) is None]
    o = objet

    if o.get("offer_id") is not None and not (isinstance(o["offer_id"], str)
                                              and _IDENTIFIANT.fullmatch(o["offer_id"])):
        motifs.append("format_invalide:offer_id")
    if o.get("supplier_id") is not None and o["supplier_id"] not in fournisseurs:
        motifs.append("fournisseur_inconnu")
    if o.get("product_id") is not None:
        if not est_entier(o["product_id"]):
            motifs.append("type_invalide:product_id")
        elif o["product_id"] not in produits:
            motifs.append("produit_hors_catalogue")
    for champ in ("price_cents", "available_units"):
        if o.get(champ) is not None:
            if not est_entier(o[champ]):
                motifs.append(f"type_invalide:{champ}")
            elif o[champ] < 0:
                motifs.append(f"valeur_negative:{champ}")
    if o.get("currency") is not None and o["currency"] != "EUR":
        motifs.append("devise_invalide")

    jour = None
    if o.get("observed_on") is not None:
        brut = o["observed_on"]
        if not isinstance(brut, str) or not _DATE_ISO.fullmatch(brut):
            motifs.append("format_invalide:observed_on")
        else:
            try:
                jour = date.fromisoformat(brut)
            except ValueError:
                motifs.append("date_inexistante:observed_on")
            else:
                if jour > aujourd_hui:
                    motifs.append("date_future:observed_on")

    if motifs:
        return None, motifs
    offre = {c: o[c] for c in CHAMPS}
    offre["observed_on"] = jour  # conversion texte ISO -> date
    return offre, []


@dataclass
class Bilan:
    fichier: str
    sha256: str
    run_s3: str | None
    lot_id: int | None = None
    statut: str = "en_cours"
    lignes_lues: int = 0
    inserees: int = 0
    mises_a_jour: int = 0
    reutilisees: int = 0
    rejetees: int = 0
    motifs: Counter = field(default_factory=Counter)
    erreur: str | None = None
    offres_en_base: int | None = None

    @property
    def acceptees(self) -> int:
        return self.inserees + self.mises_a_jour + self.reutilisees

    def afficher(self) -> str:
        lignes = [
            f"Lot {self.lot_id if self.lot_id is not None else '-'} · {self.statut.upper()} · {self.fichier}",
            f"  SHA-256   : {self.sha256}" + (f" · run S3 {self.run_s3}" if self.run_s3 else ""),
            f"  Lues      : {self.lignes_lues} = {self.acceptees} acceptées + {self.rejetees} rejetées",
            f"  Acceptées : {self.inserees} insérées, {self.mises_a_jour} mises à jour,"
            f" {self.reutilisees} réutilisées (déjà présentes à l'identique)"
            + (" · ANNULÉES par ROLLBACK, rien n'est écrit" if self.statut != "termine" else ""),
            f"  Rejets    : {dict(sorted(self.motifs.items())) or 'aucun'}",
        ]
        if self.offres_en_base is not None:
            lignes.append(f"  En base   : {self.offres_en_base} observations dans fournisseur.offres")
        if self.erreur:
            lignes.append(f"  Erreur    : {self.erreur}")
        return "\n".join(lignes)


def lire_manifeste(fichier: Path, empreinte: str) -> str | None:
    """Run S3 d'origine si le manifeste publié correspond bien à ce fichier."""
    manifeste = fichier.with_name("offres.manifest.json")
    if fichier.name != "offres.jsonl" or not manifeste.exists():
        return None
    try:
        contenu = json.loads(manifeste.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return contenu.get("run") if contenu.get("sha256") == empreinte else None


def relatif(chemin: Path) -> str:
    try:
        return str(chemin.resolve().relative_to(DOSSIER_NOVAMARKET))
    except ValueError:
        return str(chemin)


def charger(cx: psycopg.Connection, bilan: Bilan, lignes: list[str], echouer_apres: int | None) -> None:
    """Corps de la transaction. Toute exception remonte et annule le lot."""
    cx.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    cx.execute("SELECT pg_advisory_xact_lock(%s)", (VERROU,))
    produits = {r[0] for r in cx.execute("SELECT product_id FROM nova.products")}
    fournisseurs = {r[0] for r in cx.execute("SELECT supplier_id FROM fournisseur.fournisseurs")}
    aujourd_hui = cx.execute("SELECT current_date").fetchone()[0]
    if not produits:
        raise RuntimeError("catalogue nova.products vide : rejouer S1/S2 avant S4")

    bilan.lot_id = cx.execute(
        "INSERT INTO fournisseur.lots (fichier, sha256, run_s3, statut) "
        "VALUES (%s, %s, %s, 'en_cours') RETURNING lot_id",
        (bilan.fichier, bilan.sha256, bilan.run_s3)).fetchone()[0]

    vus: dict[tuple[str, date], int] = {}
    ecritures = 0
    for numero, texte in enumerate(lignes, start=1):
        bilan.lignes_lues += 1
        try:
            objet = json.loads(texte)
        except json.JSONDecodeError:
            offre, motifs = None, ["json_invalide"]
            objet = None
        else:
            offre, motifs = controler(objet, produits, fournisseurs, aujourd_hui)
        if offre is not None:
            cle = (offre["offer_id"], offre["observed_on"])
            if cle in vus:
                offre, motifs = None, [f"doublon_dans_lot:ligne_{vus[cle]}"]
            else:
                vus[cle] = numero

        if offre is None:
            bilan.rejetees += 1
            bilan.motifs.update(m.split(":ligne_")[0] for m in motifs)
            cle_id = objet.get("offer_id") if isinstance(objet, dict) else None
            cx.execute("INSERT INTO fournisseur.lot_lignes "
                       "(lot_id, numero_ligne, offer_id, action, motifs, ligne_brute) "
                       "VALUES (%s, %s, %s, 'rejetee', %s, %s)",
                       (bilan.lot_id, numero, cle_id if isinstance(cle_id, str) else None,
                        motifs, texte))
            continue

        resultat = cx.execute(UPSERT, {**offre, "lot": bilan.lot_id}).fetchone()
        if resultat is None:
            action = "reutilisee"
            bilan.reutilisees += 1
        elif resultat[0]:
            action = "inseree"
            bilan.inserees += 1
        else:
            action = "mise_a_jour"
            bilan.mises_a_jour += 1
        cx.execute("INSERT INTO fournisseur.lot_lignes "
                   "(lot_id, numero_ligne, offer_id, observed_on, action) VALUES (%s, %s, %s, %s, %s)",
                   (bilan.lot_id, numero, offre["offer_id"], offre["observed_on"], action))
        ecritures += 1
        if echouer_apres is not None and ecritures >= echouer_apres:
            raise PanneSimulee(f"panne simulée après {ecritures} écriture(s)")

    cx.execute("""UPDATE fournisseur.lots
                  SET statut = 'termine', termine_le = clock_timestamp(), lignes_lues = %s,
                      acceptees = %s, inserees = %s, mises_a_jour = %s, reutilisees = %s, rejetees = %s
                  WHERE lot_id = %s""",
               (bilan.lignes_lues, bilan.acceptees, bilan.inserees, bilan.mises_a_jour,
                bilan.reutilisees, bilan.rejetees, bilan.lot_id))
    bilan.offres_en_base = cx.execute("SELECT count(*) FROM fournisseur.offres").fetchone()[0]


def enregistrer_echec(dsn: str, bilan: Bilan) -> None:
    """Trace le lot annulé dans une transaction séparée, sans aucune offre."""
    try:
        with psycopg.connect(dsn, connect_timeout=5) as cx, cx.transaction():
            cx.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
            bilan.lot_id = cx.execute(
                "INSERT INTO fournisseur.lots (fichier, sha256, run_s3, statut, termine_le, erreur) "
                "VALUES (%s, %s, %s, 'annule', clock_timestamp(), %s) RETURNING lot_id",
                (bilan.fichier, bilan.sha256, bilan.run_s3, bilan.erreur)).fetchone()[0]
            bilan.offres_en_base = cx.execute("SELECT count(*) FROM fournisseur.offres").fetchone()[0]
    except psycopg.Error as exc:
        print(f"Impossible de tracer le lot annulé : {exc}", file=sys.stderr)


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description="Charge les offres validées S3 dans fournisseur.offres.")
    a.add_argument("--fichier", type=Path,
                   help="JSONL d'entrée (défaut : ingestion/data/valid/offres.jsonl, sinon le secours)")
    a.add_argument("--essai", action="store_true", help="exécuter tout le lot puis l'annuler (ROLLBACK)")
    a.add_argument("--echouer-apres", type=int, metavar="N",
                   help="lever une erreur après N écritures pour prouver l'atomicité")
    n = a.parse_args(argv)

    dsn = os.environ.get("NOVAMARKET_DSN")
    if not dsn:
        a.error("NOVAMARKET_DSN n'est pas défini (ex. 'host=127.0.0.1 port=15432 dbname=novamarket user=atelier')")
    if "password" in dsn.lower():
        print("Attention : mot de passe dans NOVAMARKET_DSN ; préférer PGPASSFILE ou PGPASSWORD.",
              file=sys.stderr)
    fichier = n.fichier
    if fichier is None:
        fichier = ENTREE_S3 if ENTREE_S3.exists() else ENTREE_SECOURS
        if fichier == ENTREE_SECOURS:
            print("Entrée S3 absente : utilisation de transformation/secours/offres.jsonl", file=sys.stderr)
    if not fichier.is_file():
        a.error(f"fichier introuvable : {fichier}")
    if n.echouer_apres is not None and n.echouer_apres < 1:
        a.error("--echouer-apres doit être >= 1")

    contenu = fichier.read_bytes()
    empreinte = hashlib.sha256(contenu).hexdigest()
    lignes = [l for l in contenu.decode("utf-8").splitlines() if l.strip()]
    bilan = Bilan(fichier=relatif(fichier), sha256=empreinte, run_s3=lire_manifeste(fichier, empreinte))

    try:
        with psycopg.connect(dsn, connect_timeout=5) as cx:
            with cx.transaction(force_rollback=n.essai):
                charger(cx, bilan, lignes, n.echouer_apres)
            if n.essai:
                bilan.statut = "essai_annule"
                bilan.offres_en_base = cx.execute("SELECT count(*) FROM fournisseur.offres").fetchone()[0]
            else:
                bilan.statut = "termine"
    except (psycopg.Error, PanneSimulee, RuntimeError, OSError) as exc:
        bilan.statut = "annule"
        bilan.erreur = f"{type(exc).__name__}: {exc}".strip()
        if not isinstance(exc, psycopg.OperationalError):
            enregistrer_echec(dsn, bilan)
        print(bilan.afficher())
        return 1
    print(bilan.afficher())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
