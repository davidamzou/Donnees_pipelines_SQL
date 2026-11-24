# S3 · Contrat de l'API fournisseur (M1)

Relevé le 24/11/2026 sur l'API locale (`docker compose up -d --build --wait fournisseur`), base `http://127.0.0.1:18080`.

## Endpoints

| Requête | Réponse |
| --- | --- |
| `GET /health` | `200 {"status":"ok"}` |
| `GET /offers?page=N&scenario=S&run=R` | une page d'offres (ci-dessous) |
| paramètre invalide (`page` hors 1..6, scénario inconnu, `run` hors `[a-zA-Z0-9_-]{1,64}`) | `400 {"error":"parametres"}` : erreur **permanente**, ne pas réessayer |
| autre route | `404 {"error":"route"}` |

`run` identifie un essai. L'API compte les tentatives par couple (scénario, run, page) : les incidents du scénario `atelier` n'arrivent qu'à la **première** tentative d'une page. Pour les rejouer, il faut un `run` neuf.

## Enveloppe d'une page (contrat de transport)

Exemple de réponse, tronqué à une offre (les données sont fictives, rien à anonymiser) :

```json
{
  "page": 1,
  "total_pages": 6,
  "next_page": 2,
  "items": [
    {"offer_id": "O001", "supplier_id": "F01", "product_id": 1, "price_cents": 625,
     "currency": "EUR", "available_units": 2, "observed_on": "2026-11-24"}
  ]
}
```

- **Pagination** par numéro, 6 pages de 4 offres, soit 24 offres attendues.
- `next_page` vaut `page + 1`, puis `null` sur la dernière page : c'est la **condition d'arrêt** en lecture séquentielle (curseur).
- `total_pages` est connu dès la page 1. C'est ce qui permet de lancer les pages 2 à 6 en parallèle.
- Contrôles appliqués à chaque page : `page` égale à la page demandée, `total_pages` entier ≥ 1 et identique sur toutes les pages, `next_page` cohérent, `items` est une liste. Sinon la réponse est traitée comme invalide (transitoire, donc réessayée).

## Offre (contrat de données)

| Champ | Type | Règle appliquée | Motif de rejet |
| --- | --- | --- | --- |
| `offer_id` | texte | requis, `[A-Za-z0-9_-]{1,64}`, **clé métier unique** | `champ_manquant`, `type_invalide`, `doublon:offer_id` |
| `supplier_id` | texte | requis, parmi F01, F02, F03 | `fournisseur_inconnu` |
| `product_id` | entier | requis, présent dans le catalogue S2 (`s2/donnees/products.csv`, ids 1 à 24) | `type_invalide`, `produit_hors_catalogue` |
| `price_cents` | entier | requis, ≥ 0, en centimes (pas de flottant ni de texte) | `type_invalide`, `valeur_negative` |
| `currency` | texte | vaut `EUR` | `devise_invalide` |
| `available_units` | entier | requis, ≥ 0 | `type_invalide`, `valeur_negative` |
| `observed_on` | texte | date ISO `AAAA-MM-JJ` qui existe au calendrier | `format_invalide`, `date_inexistante` |

Un booléen n'est pas accepté comme entier (`true` vaut 1 en Python). Une valeur `null` donne `champ_nul:<champ>`. Toutes les fautes d'une offre sont listées, pas seulement la première. Les champs hors contrat sont retirés de `valid/`.

**Doublons.** Les offres sont examinées dans l'ordre (page, position), quel que soit l'ordre d'arrivée des pages. La première occurrence d'un `offer_id` est gardée. Les suivantes sont rejetées avec la référence de la première, ce qui rend le résultat identique d'une exécution à l'autre.

## Scénarios observés

| Scénario | Transport | Données |
| --- | --- | --- |
| `clean` | 6 × 200 | 24 offres conformes |
| `atelier` (1ʳᵉ tentative) | p2 : `429` + `Retry-After: 1` · p3 : `200` avec corps `{json-incomplet` · p4 : réponse après ≈ 1,5 s | p2 pos. 1 sans `supplier_id` · p3 pos. 2 `price_cents = "inconnu"` · p5 pos. 1 `product_id = 9999` · p6 pos. 4 copie exacte de `O001` |
| `panne` | p6 : `503` à chaque tentative | pages 1 à 5 conformes |

Un `200` ne garantit donc ni un JSON lisible (p3) ni des données correctes (4 offres non conformes livrées en `200`).
