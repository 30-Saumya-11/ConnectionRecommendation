# SonetQ - Dynamic Link Prediction (Recency-aware model + OS-inspired snapshot cache + MySQL)

## 0. NEW: Blood-donor APPLICATION
See `README_BLOOD.md`.  Commands: `blood_app.py all` and `blood_app.py web`.

## 1. Run it (5 minutes)
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt                      # matplotlib, scikit-learn
python -m unittest discover -s tests -v              # 26 tests should say OK
python run_all.py --quick                            # 3-second smoke test
python run_all.py                                    # full run on synthetic data (~30 s)
```
Results appear in `results/` (`summary.md`, CSV files, 4 PNG plots, `sonetq.db`).

## 2. Run it on REAL data (needed for your actual results)
1. Download a temporal edge list from https://snap.stanford.edu/data/index.html#temporal
   Two formats work automatically:
   * numeric files `source target unix_time` (CollegeMsg, email-Eu-core-temporal ...)
   * TSV files with a header and text node names, e.g. `soc-redditHyperlinks-body.tsv` (columns are found by name SOURCE/TARGET/TIME)
2. Put it in `data/` and run:
```bash
python run_all.py --dataset file --path data/CollegeMsg.txt                 # 24 equal time slices
python run_all.py --dataset file --path data/soc-redditHyperlinks-body.tsv --snapshot-by month --hub-cap 300
python run_all.py --dataset file --path data/CollegeMsg.txt --with-ml       # + Logistic Regression / Random Forest
```
   `--snapshot-by month` = one snapshot per calendar month (like your Phase-II Reddit figure). The LAST 6 snapshots are always the unseen future.
3. Check `results/summary.md`. If it says the best lambda/window is at the EDGE of the grid, widen the grid in `sonetq/config.py`.
4. Big graph and slow? use `--hub-cap 300` (ignores very popular nodes as middle-men; mention this approximation in your report).
5. Metrics = those of your Phase-II report: **ROC-AUC, Average Precision, Hits@K** (+ Precision@K), plus prediction time and data-access time.
   Positives = true new links of the future snapshot; negatives = random pairs that never become links (same sample for every method).
   Hits@K = share of positives scored above the K-th best negative (OGB style; K = `hits_k` in config.py).

## 3. Use MySQL instead of SQLite
```bash
pip install mysql-connector-python
# create the database once:  CREATE DATABASE sonetq;
export SONETQ_MYSQL_USER=root SONETQ_MYSQL_PASSWORD=yourpass     # Windows: set instead of export
python run_all.py --backend mysql
```
(The MySQL path was written to mirror the SQLite one but could not be tested in the build environment - run it once and tell your team if anything errors.)

## 4. Folder map
| file | what it does | plan step |
|---|---|---|
| `sonetq/dataset.py` | load edge list / make synthetic data, cut into 24 snapshots | 4-5 |
| `sonetq/linkpred.py` | CN, Jaccard, Adamic-Adar, PA; dynamic baseline; recency-weighted model; metrics | 6-9, 14-16 |
| `sonetq/db.py` | MySQL/SQLite tables, indexes, transactions | 20-22 |
| `sonetq/cache.py` | LRU/FIFO snapshot cache with hit/miss counters | 17-19 |
| `sonetq/experiments.py` | 18->6 protocol, tuning, experiments A-D, cache sweep, index benchmark | 10-13, 19, 22 |
| `run_all.py` | runs everything, writes tables + plots | all |

### Who owns what (matches the pending-task table of the Phase-II report)
| member | pending task in report | files |
|---|---|---|
| Saumya Goswami | recency-aware model + comparison with baselines | `linkpred.py` (recency functions), `Workbench.recency_predictor / tune_recency` |
| Manvi Agarwal | MySQL storage + snapshot cache | `db.py`, `cache.py`, `sql/schema_mysql.sql`, `cache_sweep`, `index_benchmark` |
| Kavya Rathi | temporal evaluation, benchmarking, result analysis, documentation | `dataset.py` (snapshots), `experiments.py` (protocol, metrics), `reporting.py`, `results/` |

### Plugging in YOUR existing code (GCN, GraphSAGE, XGBoost from the GitHub repo)
Every model is just a function `fn(store, s, seen_pairs) -> {(u, v): score}` where `store.get(i)` returns the edges of snapshot i.
Wrap your model in such a function (train on snapshots < s only, score candidate pairs) and call
`wb.run("my GNN", fn, wb.test_steps, wb.direct_store())` - it then gets the same chronological protocol, database, cache and metrics.
| `tests/test_core.py` | correctness tests | - |

## 5. Method in one paragraph
Snapshots 1-18 are history; 19-24 are the unseen future. To predict snapshot *s* we use only snapshots 1..s-1.
A "true new link" is a pair active in snapshot *s* that was never connected earlier and whose both users already exist.
All methods rank candidate pairs (pairs sharing a neighbour, not yet connected) and we score the top-K with Precision/Recall/F1.
**Static**: merge all history into one graph, score with Adamic-Adar. **Dynamic baseline**: Adamic-Adar per snapshot, average over the last M snapshots.
**Recency-aware**: edge weight = exp(-lambda x age), then one weighted Adamic-Adar pass. lambda, M and window are chosen on snapshots 13-18 only.
**Cache**: models read snapshots via `SnapshotStore`; a hit avoids a database query.

## 6. Honest limitations (write these in your report)
* The dynamic baseline here is a SIMPLIFIED score-averaging method inspired by time-series link prediction - confirm with your mentor which published method you must reproduce.
* "Static" = aggregated union of history, re-computed from the database at each step. Updating-scheme (expanding window) must be confirmed with your mentor.
* The cache is application-level and OS-*inspired*; it does not change the operating system.
* Synthetic data only tests the pipeline. Its numbers prove nothing about real networks.
* SQLite/MySQL timings depend on your machine; small datasets show small differences. Report hardware.
