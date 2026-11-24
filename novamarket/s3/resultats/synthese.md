| Phase | Requête | Nœud | 1er passage (ms) | Répétitions (ms) | Médiane (ms) | shared hit / read (médiane) |
|---|---|---|---:|---|---:|---|
| avant_index | QA_selectif | Parallel Seq Scan | 113.04 | 137.38 / 146.50 / 111.32 | **137.38** | 96 / 63648 |
| avant_index | QB_large | Parallel Seq Scan | 447.11 | 441.03 / 411.94 / 447.95 | **441.03** | 96 / 63648 |
| apres_index | QA_selectif | Index Scan | 1.20 | 0.17 / 0.14 / 0.20 | **0.17** | 103 / 0 |
| apres_index | QB_large | Parallel Seq Scan | 682.03 | 553.17 / 508.47 / 479.80 | **508.47** | 192 / 63552 |
| apres_index | QB_force_index | Parallel Bitmap Heap Scan | 697.55 | 678.33 / 822.88 / 787.57 | **787.57** | 0 / 71694 |
