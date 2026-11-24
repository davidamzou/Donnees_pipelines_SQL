"""Collecteur asynchrone des offres fournisseurs NovaMarket (S3).

Exemples, depuis `novamarket/` avec le venv actif :

    python ingestion/src/collecteur.py --scenario clean
    python ingestion/src/collecteur.py --scenario clean --mode sequentiel
    python ingestion/src/collecteur.py --scenario atelier --run groupe01-essai01
    python ingestion/src/collecteur.py --scenario panne

Déroulé :
1. page 1 seule, pour lire `total_pages` ;
2. pages 2..N en parallèle, bornées par un sémaphore (`--concurrence`) ;
3. chaque appel est réessayé au plus `--tentatives` fois en cas d'erreur
   transitoire (timeout, connexion, 429, 5xx, JSON ou enveloppe invalide),
   avec `Retry-After` s'il est fourni, sinon un backoff exponentiel ;
4. si une page manque, le lot est déclaré en échec et rien n'est publié ;
5. sinon les offres sont validées dans l'ordre (page, position), puis
   `valid/offres.jsonl` est remplacé de façon atomique.

Codes de sortie : 0 lot publié, 1 collecte en échec (rien publié), 2 usage.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from journalisation import Bilan, configurer_journal, horodatage  # noqa: E402
from validation import Validateur, charger_catalogue  # noqa: E402

DOSSIER_INGESTION = Path(__file__).resolve().parents[1]
DOSSIER_NOVAMARKET = DOSSIER_INGESTION.parent
CATALOGUE_DEFAUT = DOSSIER_NOVAMARKET / "s2" / "donnees" / "products.csv"
SCENARIOS = ("clean", "atelier", "panne")
STATUTS_TRANSITOIRES = {429, 500, 502, 503, 504}
_RUN_VALIDE = re.compile(r"[a-zA-Z0-9_-]{1,64}")


class ErreurTransitoire(Exception):
    """Incident qui peut disparaître si l'on réessaie plus tard."""

    def __init__(self, motif: str, attente_imposee: float | None = None):
        super().__init__(motif)
        self.motif = motif
        self.attente_imposee = attente_imposee


class ErreurPermanente(Exception):
    """Incident qu'un nouvel essai ne corrigera pas (4xx hors 429)."""

    def __init__(self, motif: str):
        super().__init__(motif)
        self.motif = motif


class EchecPage(Exception):
    def __init__(self, page: int, motif: str, tentatives: int):
        super().__init__(f"page {page} : {motif} après {tentatives} tentative(s)")
        self.page = page
        self.motif = motif


@dataclass
class Parametres:
    base_url: str
    scenario: str
    run: str
    mode: str
    concurrence: int
    tentatives: int
    timeout_s: float
    attente_max_s: float
    backoff_s: float
    sortie: Path
    catalogue: Path
    ecraser: bool
    verbeux: bool


def lire_retry_after(valeur: str | None) -> float | None:
    """`Retry-After` en secondes (la forme date HTTP est aussi acceptée)."""
    if not valeur:
        return None
    try:
        return max(0.0, float(valeur))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        cible = parsedate_to_datetime(valeur)
        return max(0.0, cible.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def verifier_enveloppe(corps, page: int) -> None:
    """Contrat de transport d'une page : champs de pagination et liste d'items."""
    if not isinstance(corps, dict):
        raise ErreurTransitoire("enveloppe_invalide")
    total = corps.get("total_pages")
    suivante = corps.get("next_page")
    if corps.get("page") != page or not isinstance(total, int) or total < 1 \
            or not isinstance(corps.get("items"), list):
        raise ErreurTransitoire("enveloppe_invalide")
    attendu = page + 1 if page < total else None
    if suivante != attendu:
        raise ErreurTransitoire("pagination_incoherente")


class FichierJSONL:
    """Écriture ligne à ligne, UTF-8, un objet JSON par ligne."""

    def __init__(self, chemin: Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin = chemin
        self._f = open(chemin, "w", encoding="utf-8", newline="\n")

    def ecrire(self, objet: dict) -> None:
        self._f.write(json.dumps(objet, ensure_ascii=False) + "\n")
        self._f.flush()

    def fermer(self) -> None:
        self._f.close()


def ecrire_jsonl_atomique(chemin: Path, objets: list[dict]) -> str:
    """Écrit dans un fichier temporaire puis le renomme ; retourne le SHA-256."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(f".{chemin.name}.tmp")
    contenu = "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objets).encode("utf-8")
    with open(temporaire, "wb") as f:
        f.write(contenu)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporaire, chemin)
    return hashlib.sha256(contenu).hexdigest()


class Collecteur:
    def __init__(self, p: Parametres, bilan: Bilan, logger, raw: FichierJSONL):
        self.p = p
        self.bilan = bilan
        self.log = logger
        self.raw = raw
        self.limite = asyncio.Semaphore(p.concurrence)
        self.en_vol = 0
        self.session: aiohttp.ClientSession | None = None

    async def _un_appel(self, page: int, tentative: int) -> dict:
        """Une requête HTTP sous le sémaphore. Lève une erreur classée."""
        params = {"page": str(page), "scenario": self.p.scenario, "run": self.p.run}
        async with self.limite:
            self.en_vol += 1
            self.bilan.concurrence_observee = max(self.bilan.concurrence_observee, self.en_vol)
            self.bilan.requetes_http += 1
            self.bilan.tentatives_par_page[page] = tentative
            t0 = time.perf_counter()
            self.log.debug("requete_envoyee", extra={"page": page, "tentative": tentative,
                                                     "en_vol": self.en_vol})
            try:
                async with self.session.get(f"{self.p.base_url}/offers", params=params) as rep:
                    texte = await rep.text()
                    statut = rep.status
                    retry_after = rep.headers.get("Retry-After")
            except asyncio.TimeoutError:
                raise ErreurTransitoire("timeout") from None
            except aiohttp.ClientError as exc:
                raise ErreurTransitoire(f"connexion:{type(exc).__name__}") from None
            finally:
                self.en_vol -= 1

        duree_ms = round((time.perf_counter() - t0) * 1000)
        try:
            corps = json.loads(texte)
        except json.JSONDecodeError:
            corps = None
        # raw/ garde tout ce qui a été reçu, y compris les réponses refusées.
        self.raw.ecrire({"run": self.p.run, "scenario": self.p.scenario, "page": page,
                         "tentative": tentative, "recu_le": horodatage(), "statut_http": statut,
                         "duree_ms": duree_ms, "retry_after": retry_after,
                         "corps": corps,
                         "corps_brut": texte if corps is None else None})
        self.log.debug("reponse_recue", extra={"page": page, "tentative": tentative,
                                               "statut_http": statut, "duree_ms": duree_ms})
        if statut in STATUTS_TRANSITOIRES:
            raise ErreurTransitoire(f"http_{statut}", lire_retry_after(retry_after))
        if statut != 200:
            raise ErreurPermanente(f"http_{statut}")
        if corps is None:
            raise ErreurTransitoire("json_invalide")
        verifier_enveloppe(corps, page)
        return corps

    def _attente(self, tentative: int, erreur: ErreurTransitoire) -> float:
        if erreur.attente_imposee is not None:
            return min(erreur.attente_imposee, self.p.attente_max_s)
        base = self.p.backoff_s * 2 ** (tentative - 1)
        return min(base * (1 + random.random() * 0.25), self.p.attente_max_s)

    async def lire_page(self, page: int) -> dict:
        """Lit une page avec reprises bornées ; l'attente se fait hors sémaphore."""
        for tentative in range(1, self.p.tentatives + 1):
            try:
                corps = await self._un_appel(page, tentative)
            except ErreurPermanente as exc:
                self.bilan.incidents[exc.motif] += 1
                self.log.error("page_en_echec", extra={"page": page, "tentative": tentative,
                                                       "motif": exc.motif, "nature": "permanente"})
                raise EchecPage(page, exc.motif, tentative) from None
            except ErreurTransitoire as exc:
                self.bilan.incidents[exc.motif] += 1
                if tentative == self.p.tentatives:
                    self.log.error("page_en_echec", extra={"page": page, "tentative": tentative,
                                                           "motif": exc.motif, "nature": "transitoire_epuisee"})
                    raise EchecPage(page, exc.motif, tentative) from None
                attente = self._attente(tentative, exc)
                self.bilan.reprises += 1
                self.log.warning("reprise_programmee", extra={
                    "page": page, "tentative": tentative, "motif": exc.motif,
                    "attente_s": round(attente, 3),
                    "source_attente": "retry-after" if exc.attente_imposee is not None else "backoff"})
                await asyncio.sleep(attente)
            else:
                self.bilan.pages_recues += 1
                self.log.info("page_recuperee", extra={"page": page, "tentative": tentative,
                                                       "lignes": len(corps["items"])})
                return corps
        raise AssertionError("inatteignable")

    async def collecter(self) -> tuple[dict[int, dict], list[EchecPage]]:
        timeout = aiohttp.ClientTimeout(total=self.p.timeout_s)
        connecteur = aiohttp.TCPConnector(limit=self.p.concurrence)
        async with aiohttp.ClientSession(timeout=timeout, connector=connecteur) as session:
            self.session = session
            if self.p.mode == "sequentiel":
                return await self._sequentiel()
            return await self._concurrent()

    async def _sequentiel(self):
        """Suit le curseur `next_page` une page après l'autre (référence de durée)."""
        pages, page = {}, 1
        while page is not None:
            if page in pages:
                raise RuntimeError(f"boucle de pagination sur la page {page}")
            try:
                corps = await self.lire_page(page)
            except EchecPage as echec:
                return pages, [echec]
            pages[page] = corps
            self.bilan.pages_attendues = corps["total_pages"]
            page = corps["next_page"]
        return pages, []

    async def _concurrent(self):
        try:
            premiere = await self.lire_page(1)
        except EchecPage as echec:
            return {}, [echec]
        total = premiere["total_pages"]
        self.bilan.pages_attendues = total
        resultats = await asyncio.gather(*(self.lire_page(n) for n in range(2, total + 1)),
                                         return_exceptions=True)
        pages, echecs = {1: premiere}, []
        for numero, resultat in zip(range(2, total + 1), resultats):
            if isinstance(resultat, EchecPage):
                echecs.append(resultat)
            elif isinstance(resultat, BaseException):
                raise resultat
            else:
                pages[numero] = resultat
        incoherents = [n for n, c in pages.items() if c["total_pages"] != total]
        if incoherents:
            raise RuntimeError(f"total_pages variable entre les pages {sorted(incoherents)}")
        return pages, echecs


def preparer_sorties(p: Parametres) -> dict[str, Path]:
    chemins = {
        "raw": p.sortie / "raw" / f"{p.run}.jsonl",
        "valid_run": p.sortie / "valid" / "runs" / f"{p.run}.jsonl",
        "valid_publie": p.sortie / "valid" / "offres.jsonl",
        "manifeste": p.sortie / "valid" / "offres.manifest.json",
        "rejected": p.sortie / "rejected" / f"{p.run}.jsonl",
        "journal": p.sortie / "logs" / f"{p.run}.log",
        "bilan": p.sortie / "bilans" / f"{p.run}.json",
    }
    if chemins["raw"].exists() or chemins["bilan"].exists():
        if not p.ecraser:
            print(f"Le run « {p.run} » existe déjà dans {relatif(p.sortie)}. Choisir un nouveau "
                  "--run (l'API rejoue alors ses incidents) ou --ecraser.", file=sys.stderr)
            raise SystemExit(2)
        for cle in ("raw", "valid_run", "rejected", "journal", "bilan"):
            chemins[cle].unlink(missing_ok=True)
    return chemins


def relatif(chemin: Path) -> str:
    try:
        return str(chemin.relative_to(DOSSIER_NOVAMARKET))
    except ValueError:
        return str(chemin)


async def executer(p: Parametres) -> int:
    chemins = preparer_sorties(p)
    logger = configurer_journal(chemins["journal"], p.verbeux)
    bilan = Bilan(run=p.run, scenario=p.scenario, concurrence_max=p.concurrence,
                  tentatives_max=p.tentatives, timeout_s=p.timeout_s)
    bilan.fichiers = {"raw": relatif(chemins["raw"]), "journal": relatif(chemins["journal"]),
                      "bilan": relatif(chemins["bilan"])}
    catalogue = charger_catalogue(p.catalogue)
    logger.info("collecte_demarree", extra={"run": p.run, "scenario": p.scenario, "mode": p.mode,
                                            "concurrence": p.concurrence, "tentatives": p.tentatives,
                                            "timeout_s": p.timeout_s, "base_url": p.base_url,
                                            "produits_catalogue": len(catalogue)})
    raw = FichierJSONL(chemins["raw"])
    try:
        pages, echecs = await Collecteur(p, bilan, logger, raw).collecter()
    except Exception as exc:  # incohérence de pagination ou bug : jamais publié
        pages, echecs = {}, []
        bilan.erreur = f"{type(exc).__name__}: {exc}"
        logger.exception("collecte_interrompue")
    finally:
        raw.fermer()

    code = 1
    if echecs or bilan.erreur or not bilan.controles()["toutes_pages_recues"]:
        bilan.pages_en_echec = sorted(e.page for e in echecs)
        bilan.erreur = bilan.erreur or "; ".join(str(e) for e in echecs) or "pages manquantes"
        bilan.cloturer("echec")
        logger.error("lot_non_publie", extra={"pages_en_echec": bilan.pages_en_echec,
                                              "pages_recues": bilan.pages_recues,
                                              "raison": bilan.erreur})
    else:
        validateur = Validateur(catalogue)
        for numero in sorted(pages):
            for position, offre in enumerate(pages[numero]["items"], start=1):
                bilan.lignes_examinees += 1
                if not validateur.examiner(numero, position, offre):
                    rejet = validateur.rejets[-1]
                    bilan.motifs_rejet.update(rejet["motifs"])
                    logger.warning("offre_rejetee", extra={
                        "page": numero, "position": position, "motifs": rejet["motifs"],
                        "offer_id": offre.get("offer_id") if isinstance(offre, dict) else None})
        bilan.lignes_valides = len(validateur.valides)
        bilan.lignes_rejetees = len(validateur.rejets)
        ecrire_jsonl_atomique(chemins["rejected"], [{"run": p.run, **r} for r in validateur.rejets])
        empreinte = ecrire_jsonl_atomique(chemins["valid_run"], validateur.valides)
        bilan.fichiers.update(valid=relatif(chemins["valid_publie"]),
                              valid_run=relatif(chemins["valid_run"]),
                              rejected=relatif(chemins["rejected"]))
        if all(bilan.controles().values()):
            # Publication : copie complète puis renommage, jamais un fichier partiel.
            temporaire = chemins["valid_publie"].with_name(".offres.jsonl.tmp")
            shutil.copyfile(chemins["valid_run"], temporaire)
            os.replace(temporaire, chemins["valid_publie"])
            bilan.publie = True
            bilan.cloturer("succes")
            manifeste = {"run": p.run, "scenario": p.scenario, "publie_le": bilan.fin,
                         "lignes": bilan.lignes_valides, "sha256": empreinte,
                         "source": bilan.fichiers["valid_run"], "bilan": bilan.fichiers["bilan"]}
            ecrire_jsonl_atomique(chemins["manifeste"], [manifeste])
            logger.info("lot_publie", extra={"fichier": bilan.fichiers["valid"],
                                             "lignes": bilan.lignes_valides, "sha256": empreinte})
            code = 0
        else:
            bilan.erreur = f"contrôles en échec : {bilan.controles()}"
            bilan.cloturer("echec")
            logger.error("lot_non_publie", extra={"raison": bilan.erreur})

    chemins["bilan"].parent.mkdir(parents=True, exist_ok=True)
    chemins["bilan"].write_text(json.dumps(bilan.en_dict(), ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    logger.debug("bilan", extra=bilan.en_dict())  # fichier journal ; la console a le résumé
    print(bilan.resume())
    return code


def analyser_arguments(argv=None) -> Parametres:
    port = os.environ.get("NOVAMARKET_API_PORT", "18080")
    a = argparse.ArgumentParser(description="Collecte asynchrone des offres fournisseurs NovaMarket.")
    a.add_argument("--scenario", choices=SCENARIOS, default="atelier")
    a.add_argument("--run", help="identifiant d'essai (défaut : <scenario>-<horodatage>)")
    a.add_argument("--mode", choices=("concurrent", "sequentiel"), default="concurrent")
    a.add_argument("--concurrence", type=int, default=3, help="requêtes simultanées max (défaut 3)")
    a.add_argument("--tentatives", type=int, default=4, help="essais HTTP max par page (défaut 4)")
    a.add_argument("--timeout", type=float, default=1.0, help="délai total par requête, s (défaut 1.0)")
    a.add_argument("--attente-max", type=float, default=5.0, help="attente max entre essais, s")
    a.add_argument("--backoff", type=float, default=0.25, help="base du backoff exponentiel, s")
    a.add_argument("--base-url", default=os.environ.get("NOVAMARKET_API_URL", f"http://127.0.0.1:{port}"))
    a.add_argument("--sortie", type=Path, default=DOSSIER_INGESTION / "data")
    a.add_argument("--catalogue", type=Path, default=CATALOGUE_DEFAUT,
                   help="CSV du catalogue S2 (colonne product_id)")
    a.add_argument("--ecraser", action="store_true", help="réutiliser un --run déjà présent")
    a.add_argument("-v", "--verbeux", action="store_true", help="afficher chaque requête")
    n = a.parse_args(argv)

    run = n.run or f"{n.scenario}-{datetime.now():%Y%m%d-%H%M%S}"
    if not _RUN_VALIDE.fullmatch(run):
        a.error("--run : 1 à 64 caractères parmi lettres, chiffres, _ et -")
    if not 1 <= n.concurrence <= 20:
        a.error("--concurrence doit être compris entre 1 et 20")
    if not 1 <= n.tentatives <= 10:
        a.error("--tentatives doit être compris entre 1 et 10")
    if not 0 < n.timeout <= 30 or not 0 <= n.attente_max <= 60 or n.backoff < 0:
        a.error("--timeout, --attente-max ou --backoff hors bornes")
    concurrence = 1 if n.mode == "sequentiel" else n.concurrence
    return Parametres(base_url=n.base_url.rstrip("/"), scenario=n.scenario, run=run, mode=n.mode,
                      concurrence=concurrence, tentatives=n.tentatives, timeout_s=n.timeout,
                      attente_max_s=n.attente_max, backoff_s=n.backoff, sortie=n.sortie.resolve(),
                      catalogue=n.catalogue, ecraser=n.ecraser, verbeux=n.verbeux)


def main(argv=None) -> int:
    return asyncio.run(executer(analyser_arguments(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
