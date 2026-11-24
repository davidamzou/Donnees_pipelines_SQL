# NovaMarket S3 — Solution : ingestion asynchrone

Collecteur `aiohttp` / `asyncio` des offres fournisseurs : pagination, concurrence bornée, reprises, validation et traces `raw / valid / rejected`. Le contrat relevé en M1 est dans [CONTRAT.md](CONTRAT.md).

| Fichier | Rôle |
| --- | --- |
| [`src/collecteur.py`](src/collecteur.py) | M2–M3 : pagination, sémaphore, timeouts, classement des erreurs, reprises, publication atomique |
| [`src/validation.py`](src/validation.py) | M4 : règles du contrat, motifs de rejet, doublons |
| [`src/journalisation.py`](src/journalisation.py) | M4 : journal JSONL, compteurs du bilan, contrôles de cohérence |
| [`tests/test_validation.py`](tests/test_validation.py) | 18 tests unitaires des règles (sans réseau) |
| [`tests/test_scenarios.py`](tests/test_scenarios.py) | 4 tests d'intégration contre l'API (clean, atelier, panne, non-écrasement) |

## Mode d'emploi

Depuis `novamarket/` :

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-v3.txt
docker compose up -d --build --wait fournisseur
python ingestion/tests/disponibilite.py
```

### Sans Python 3.12 sur le poste : service Compose `collecteur`

Le [Dockerfile](api/Dockerfile) a deux cibles construites sur la même base `python:3.12-slim` épinglée :

| Cible | Service | Contenu |
| --- | --- | --- |
| `fournisseur` | API de simulation | `server.py` seul, utilisateur non privilégié, aucune dépendance ajoutée |
| `collecteur` | client | dépendances de `requirements-v3.txt` installées dans l'image ; `ingestion/` et `s2/donnees/` (lecture seule) montés dans `/work` |

Le code est monté, pas copié : une modification de `src/` est prise en compte sans reconstruire. On reconstruit seulement si `requirements-v3.txt` change. Le service démarre le fournisseur tout seul et attend qu'il soit sain (`depends_on`) :

```bash
docker compose --profile ingestion build
```

```bash
docker compose run --rm collecteur --scenario atelier
```

```bash
docker compose run --rm collecteur --scenario clean --mode sequentiel
```

```bash
docker compose run --rm --entrypoint python collecteur -m unittest discover -s ingestion/tests -v
```

Les arguments après `collecteur` sont ceux du collecteur ; l'URL de l'API (`http://fournisseur:8080`) est fournie par `NOVAMARKET_API_URL`. Les fichiers sont écrits avec l'UID 1000 par défaut ; sous Linux, si ton UID est différent, exporter `NOVAMARKET_UID=$(id -u) NOVAMARKET_GID=$(id -g)` avant `docker compose run`.

### Collecter avec le venv

Mêmes options, avec `python ingestion/src/collecteur.py` à la place de `docker compose run --rm collecteur` :

```bash
python ingestion/src/collecteur.py --scenario clean
```

```bash
python ingestion/src/collecteur.py --scenario clean --mode sequentiel
```

```bash
python ingestion/src/collecteur.py --scenario atelier --run groupe01-essai01
```

```bash
python ingestion/src/collecteur.py --scenario panne
```

```bash
python -m unittest discover -s ingestion/tests -v
```

| Option | Défaut | Effet |
| --- | --- | --- |
| `--scenario` | `atelier` | `clean`, `atelier` ou `panne` |
| `--run` | `<scenario>-<horodatage>` | identifiant d'essai ; un run existant est refusé (code 2) sauf `--ecraser` |
| `--mode` | `concurrent` | `sequentiel` suit `next_page` une page après l'autre |
| `--concurrence` | 3 | requêtes simultanées max (sémaphore + `TCPConnector(limit=…)`) |
| `--tentatives` | 4 | essais HTTP max par page |
| `--timeout` | 1,0 s | délai total d'une requête |
| `--backoff` / `--attente-max` | 0,25 s / 5 s | base du backoff exponentiel / plafond de toute attente, `Retry-After` compris |
| `-v` | | affiche chaque requête et réponse |

Codes de sortie : `0` lot publié, `1` collecte en échec (rien publié), `2` erreur d'usage.

## Sorties

Toutes en JSONL UTF-8 (un objet par ligne), un fichier par run, sous `ingestion/data/` :

| Chemin | Contenu | Écrit quand |
| --- | --- | --- |
| `raw/<run>.jsonl` | chaque réponse HTTP reçue : page, tentative, statut, durée, `Retry-After`, corps JSON ou texte brut s'il est illisible | toujours, au fil de l'eau |
| `rejected/<run>.jsonl` | page, position (1 = premier élément de `items`), motifs, objet brut, première occurrence pour un doublon | collecte complète |
| `valid/runs/<run>.jsonl` | offres conformes, champs du contrat uniquement | collecte complète |
| `valid/offres.jsonl` | **lot publié pour S4**, copie de `valid/runs/<run>.jsonl` remplacée par renommage atomique | collecte complète **et** tous les contrôles du bilan à `ok` |
| `valid/offres.manifest.json` | run source, nombre de lignes, SHA-256, date de publication | avec la publication |
| `logs/<run>.log` | journal JSONL : `page_recuperee`, `reprise_programmee`, `page_en_echec`, `offre_rejetee`, `lot_publie` / `lot_non_publie`, `bilan` | toujours |
| `bilans/<run>.json` | compteurs et contrôles (ci-dessous) | toujours |

Un lot incomplet ne touche ni `valid/offres.jsonl` ni le manifeste. S4 continue de lire le dernier lot complet, et le manifeste indique de quel run il vient.

## M2 — Collecte concurrente

1. La page 1 est lue seule, pour connaître `total_pages`.
2. Les pages 2 à 6 partent ensuite en même temps (`asyncio.gather`), mais au plus `--concurrence` requêtes sont en vol, grâce à un `asyncio.Semaphore`. Le compteur `concurrence_observee` du bilan mesure le maximum réellement atteint.
3. Une seule `ClientSession` est réutilisée pour toutes les requêtes.
4. Chaque page garde son numéro jusqu'à la validation, qui suit l'ordre (page, position) et non l'ordre d'arrivée.

Mesures, latence API 0,12 s, run neuf à chaque ligne (`ingestion/data/bilans/` pour les runs `ref-*`) :

| Scénario | Séquentiel | Concurrence 1 | Concurrence 3 | Concurrence 6 | Requêtes HTTP |
| --- | ---: | ---: | ---: | ---: | ---: |
| `clean` | 0,77 s | 0,76 s | 0,39 s | 0,27 s | 6 |
| `atelier` | 3,63 s | 2,04 s | 1,58 s | 1,54 s | 9 (6 pages + 3 reprises) |

- **clean** : en séquentiel, 6 × 0,12 s ≈ 0,72 s, plus le surcoût. Avec 3 requêtes en vol, la page 1 puis deux vagues font 3 × 0,12 ≈ 0,36 s. Au-delà de 5, aucun gain : il ne reste que 5 pages après la page 1, et la concurrence observée plafonne à 5/6.
- **atelier** : le plancher vient des incidents, pas de la concurrence. La page 2 attend `Retry-After: 1`, la page 4 consomme 1 s de timeout puis un backoff, soit ≈ 0,12 + 1,0 + 0,25 + 0,12 ≈ 1,5 s. Passer de 3 à 6 ne change presque rien.
- **Concurrence 1 ≠ séquentiel** : l'attente avant une reprise se fait **hors du sémaphore**. Une page qui patiente libère sa place, et les autres pages avancent pendant ce temps (2,0 s contre 3,6 s).

## M3 — Fiabilité

| Incident | Classement | Traitement |
| --- | --- | --- |
| Timeout (`--timeout`) | transitoire | reprise après backoff `0,25 × 2^(n-1)` + 0 à 25 % d'aléa |
| Connexion refusée / coupée | transitoire | idem |
| `429` | transitoire | reprise après `Retry-After` (secondes ou date HTTP), plafonné par `--attente-max` |
| `500`, `502`, `503`, `504` | transitoire | backoff |
| `200` + JSON illisible | transitoire | backoff ; le corps brut est gardé dans `raw/` |
| `200` + enveloppe incohérente | transitoire | backoff |
| Autre `4xx` (400, 404…) | permanent | échec immédiat de la page, sans reprise |
| Offre non conforme dans un `200` | donnée invalide | aucune reprise, rejet motivé (M4) |

Le nombre d'essais par page est borné (`--tentatives`). Quand une page épuise ses essais, les autres pages vont quand même au bout : le diagnostic reste complet. Le lot est ensuite déclaré en échec.

Résultat du run `ref-atelier-c3` (journal `logs/ref-atelier-c3.log`) :

```
WARNING reprise_programmee page=2 tentative=1 motif=http_429 attente_s=1.0 source_attente=retry-after
WARNING reprise_programmee page=3 tentative=1 motif=json_invalide attente_s=0.267 source_attente=backoff
WARNING reprise_programmee page=4 tentative=1 motif=timeout attente_s=0.251 source_attente=backoff
```

Résultat du run `ref-panne-c3` : page 6 en `503` quatre fois, `page_en_echec`, puis `lot_non_publie`, code de sortie 1. `valid/offres.jsonl` reste le lot `ref-atelier-c3` publié juste avant (le manifeste le confirme).

## M4 — Validation et bilan

Règles : voir [CONTRAT.md](CONTRAT.md#offre-contrat-de-données). Sur `atelier` :

| Page | Position | `offer_id` | Motif |
| ---: | ---: | --- | --- |
| 2 | 1 | O005 | `champ_manquant:supplier_id` |
| 3 | 2 | O010 | `type_invalide:price_cents` |
| 5 | 1 | O017 | `produit_hors_catalogue` (9999) |
| 6 | 4 | O001 | `doublon:offer_id` (première occurrence p1 pos. 1) |

**24 offres examinées = 20 valides + 4 rejetées**, ce qui correspond au contrôle de complétude du livret.

Le bilan sépare les essais HTTP des offres, et vérifie quatre égalités avant toute publication :

| Contrôle | Égalité |
| --- | --- |
| `toutes_pages_recues` | pages reçues = `total_pages`, aucune page en échec |
| `lignes_equilibrees` | examinées = valides + rejetées |
| `concurrence_respectee` | concurrence observée ≤ borne |
| `requetes_coherentes` | requêtes HTTP = Σ tentatives par page, et reprises = requêtes − pages tentées |

| Run | Statut | Pages | HTTP | Reprises | Examinées | Valides | Rejetées | Durée |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ref-clean-c3` | succès | 6/6 | 6 | 0 | 24 | 24 | 0 | 0,41 s |
| `ref-clean-sequentiel` | succès | 6/6 | 6 | 0 | 24 | 24 | 0 | 0,77 s |
| `ref-atelier-c3` | succès, **publié** | 6/6 | 9 | 3 | 24 | 20 | 4 | 1,53 s |
| `ref-panne-c3` | échec, non publié | 5/6 | 9 | 3 | 0 | 0 | 0 | 2,82 s |

## Idempotence

- Un `run` déjà présent est refusé : on n'écrase pas une trace par erreur.
- Quatre collectes `atelier` avec des runs différents (séquentiel, concurrence 1, 3 et 6) ont publié un `valid/offres.jsonl` identique octet pour octet (SHA-256 `8dfc690a…b7c`). L'ordre (page, position) neutralise l'ordre d'arrivée des pages.
- `valid/offres.jsonl` est **remplacé**, jamais complété : une relance ne multiplie pas les offres.

## Limites

- Les écritures de fichiers sont synchrones dans la boucle. C'est sans effet à 24 lignes. Pour de gros volumes, il faudrait `asyncio.to_thread` ou une file d'écriture.
- Le catalogue de référence est le CSV brut S2, réduit à l'ensemble de ses `product_id` (le doublon du produit 3 n'a pas d'effet). En S4, il faudra lire `nova.products` pour garder une seule source de vérité.
- La règle `price_cents ≥ 0` accepte un prix nul, comme le contrat. Une règle métier plus stricte (prix > 0, plafond) reste à décider avec NovaMarket.
- Les durées dépendent du poste et de la latence simulée. Pour comparer deux essais, garder le même scénario et la même `NOVAMARKET_API_LATENCY`.
