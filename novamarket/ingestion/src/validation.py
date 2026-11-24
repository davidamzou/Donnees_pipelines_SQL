"""Contrôles d'une offre fournisseur et motifs de rejet.

Une offre est valide si elle respecte le contrat de données (structure puis
règles métier) et si son identifiant `offer_id` n'a pas déjà été accepté.
Toutes les fautes d'une offre sont relevées, pas seulement la première, afin
que le rejet soit complet pour le diagnostic.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Ordre de publication des champs dans valid/offres.jsonl (contrat).
CHAMPS_CONTRAT = (
    "offer_id",
    "supplier_id",
    "product_id",
    "price_cents",
    "currency",
    "available_units",
    "observed_on",
)
FOURNISSEURS_CONNUS = frozenset({"F01", "F02", "F03"})
DEVISE = "EUR"
_DATE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_IDENTIFIANT = re.compile(r"[A-Za-z0-9_-]{1,64}")


def est_entier(valeur) -> bool:
    """Entier JSON strict : `True` et `12.0` ne sont pas des entiers ici."""
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def charger_catalogue(chemin: str | Path) -> frozenset[int]:
    """Identifiants produit du catalogue S2 (`s2/donnees/products.csv`).

    Le fichier brut contient un doublon exact (`product_id = 3`) ; on ne garde
    que l'ensemble des identifiants, ce qui suffit au contrôle de référence.
    """
    identifiants = set()
    with open(chemin, newline="", encoding="utf-8") as fichier:
        for ligne in csv.DictReader(fichier):
            brut = (ligne.get("product_id") or "").strip()
            if brut.isdigit():
                identifiants.add(int(brut))
    if not identifiants:
        raise ValueError(f"catalogue vide ou illisible : {chemin}")
    return frozenset(identifiants)


def controler_offre(offre, catalogue: frozenset[int],
                    fournisseurs: frozenset[str] = FOURNISSEURS_CONNUS) -> list[str]:
    """Retourne la liste des motifs de rejet (vide si l'offre est conforme)."""
    if not isinstance(offre, dict):
        return ["structure:objet_attendu"]

    motifs = []
    for champ in CHAMPS_CONTRAT:
        if champ not in offre:
            motifs.append(f"champ_manquant:{champ}")
        elif offre[champ] is None:
            motifs.append(f"champ_nul:{champ}")

    def present(champ):
        return offre.get(champ) is not None

    for champ in ("offer_id", "supplier_id"):
        if present(champ):
            valeur = offre[champ]
            if not isinstance(valeur, str):
                motifs.append(f"type_invalide:{champ}")
            elif not _IDENTIFIANT.fullmatch(valeur):
                motifs.append(f"format_invalide:{champ}")
    if present("supplier_id") and isinstance(offre["supplier_id"], str) \
            and offre["supplier_id"] not in fournisseurs:
        motifs.append("fournisseur_inconnu")

    if present("product_id"):
        if not est_entier(offre["product_id"]):
            motifs.append("type_invalide:product_id")
        elif offre["product_id"] not in catalogue:
            motifs.append("produit_hors_catalogue")

    for champ in ("price_cents", "available_units"):
        if present(champ):
            if not est_entier(offre[champ]):
                motifs.append(f"type_invalide:{champ}")
            elif offre[champ] < 0:
                motifs.append(f"valeur_negative:{champ}")

    if present("currency") and offre["currency"] != DEVISE:
        motifs.append("devise_invalide")

    if present("observed_on"):
        valeur = offre["observed_on"]
        if not isinstance(valeur, str) or not _DATE_ISO.fullmatch(valeur):
            motifs.append("format_invalide:observed_on")
        else:
            try:
                date.fromisoformat(valeur)
            except ValueError:
                motifs.append("date_inexistante:observed_on")
    return motifs


def normaliser(offre: dict) -> dict:
    """Ne conserve que les champs du contrat, dans l'ordre du contrat."""
    return {champ: offre[champ] for champ in CHAMPS_CONTRAT}


@dataclass
class Validateur:
    """Applique les contrôles dans l'ordre des pages et détecte les doublons.

    L'ordre (page, position) rend le résultat déterministe malgré la collecte
    concurrente : la première occurrence d'un `offer_id` est conservée, les
    suivantes sont rejetées avec la référence de la première.
    """
    catalogue: frozenset[int]
    fournisseurs: frozenset[str] = FOURNISSEURS_CONNUS
    valides: list[dict] = field(default_factory=list)
    rejets: list[dict] = field(default_factory=list)
    _vus: dict[str, tuple[int, int]] = field(default_factory=dict)

    def examiner(self, page: int, position: int, offre) -> bool:
        motifs = controler_offre(offre, self.catalogue, self.fournisseurs)
        cle = offre.get("offer_id") if isinstance(offre, dict) else None
        premiere = self._vus.get(cle) if isinstance(cle, str) else None
        if premiere is not None:
            motifs.append("doublon:offer_id")
        if motifs:
            rejet = {"page": page, "position": position, "motifs": motifs, "objet": offre}
            if premiere is not None:
                rejet["premiere_occurrence"] = {"page": premiere[0], "position": premiere[1]}
            self.rejets.append(rejet)
            return False
        self._vus[cle] = (page, position)
        self.valides.append(normaliser(offre))
        return True
