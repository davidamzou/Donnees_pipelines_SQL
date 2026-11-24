# Synthèse des mesures : médiane des répétitions, premier passage exclu.
import csv, statistics, sys, collections
rows = list(csv.DictReader(open(sys.argv[1])))
g = collections.OrderedDict()
for r in rows:
    g.setdefault((r['phase'], r['requete']), []).append(r)
print("| Phase | Requête | Nœud | 1er passage (ms) | Répétitions (ms) | Médiane (ms) | shared hit / read (médiane) |")
print("|---|---|---|---:|---|---:|---|")
for (ph, q), rs in g.items():
    first = [r for r in rs if r['passage'] == 'premier']
    reps = [r for r in rs if r['passage'] != 'premier']
    t = [float(r['execution_ms']) for r in reps]
    m = statistics.median(t)
    mid = sorted(reps, key=lambda r: float(r['execution_ms']))[len(reps)//2]
    print(f"| {ph} | {q} | {reps[-1]['noeud_principal']} | {float(first[-1]['execution_ms']):.2f} | "
          f"{' / '.join(f'{x:.2f}' for x in t)} | **{m:.2f}** | {mid['shared_hit']} / {mid['shared_read']} |")
