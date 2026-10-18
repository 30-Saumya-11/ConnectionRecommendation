"""ONE command runs the whole project:     python run_all.py
Options:  --dataset file --path data/soc-redditHyperlinks-body.tsv --snapshot-by month   (real data)
          --backend mysql      use MySQL instead of SQLite
          --with-ml            also run Logistic Regression / Random Forest models
          --hub-cap 300        speed-up for big graphs      --k 300  --repeats 3  --quick
"""
import argparse
import os
import time

from sonetq.config import Config
from sonetq import dataset as ds
from sonetq.db import SnapshotDB
from sonetq.cache import SnapshotStore
from sonetq.experiments import Workbench, write_csv
from sonetq.reporting import md_table, make_plots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["synthetic", "file"], default="synthetic")
    ap.add_argument("--path", default="data/CollegeMsg.txt")
    ap.add_argument("--snapshot-by", choices=["equal", "month"], default="equal")
    ap.add_argument("--n-snapshots", type=int, default=None)
    ap.add_argument("--backend", choices=["sqlite", "mysql"], default="sqlite")
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--hub-cap", type=int, default=None)
    ap.add_argument("--repeats", type=int, default=None)
    ap.add_argument("--with-ml", action="store_true")
    ap.add_argument("--quick", action="store_true", help="small & fast (for a first smoke test)")
    a = ap.parse_args()

    cfg = Config(dataset=a.dataset, dataset_path=a.path, db_backend=a.backend, snapshot_by=a.snapshot_by)
    if a.quick:
        cfg.synth_nodes, cfg.synth_new_per_snapshot, cfg.repeats = 400, 200, 1
        cfg.k_predictions = 100
        cfg.lambda_grid, cfg.recency_window_grid, cfg.dynamic_window_grid = (0.0, 0.5), (4, 6), (2, 4)
    if a.k:
        cfg.k_predictions = a.k
    if a.n_snapshots:
        cfg.n_snapshots = a.n_snapshots
    if a.hub_cap is not None:
        cfg.hub_cap = a.hub_cap
    if a.repeats:
        cfg.repeats = a.repeats
    os.makedirs(cfg.results_dir, exist_ok=True)
    out = cfg.results_dir
    T0 = time.time()

    print("== Step 4-5: dataset -> snapshots")
    snaps, meta, names = ds.get_snapshots(cfg)
    info = ds.describe(snaps)
    print(f"   users={info['nodes']}  snapshots={cfg.n_snapshots} (history {cfg.n_history} + future {cfg.n_future})")
    print(f"   edges per snapshot: {info['edges_per_snapshot']}")

    print(f"== Phase 11: load into {cfg.db_backend} (schema + indexes)")
    if cfg.db_backend == "sqlite" and os.path.exists(cfg.sqlite_path):
        os.remove(cfg.sqlite_path)
    db = SnapshotDB(cfg.db_backend, cfg.sqlite_path, cfg.mysql)
    db.create_schema()
    db.load(snaps, meta, names)
    db.create_indexes()
    print(f"   rows in edges table: {db.count_edges()}")

    wb = Workbench(snaps, db, cfg)
    test_steps = wb.test_steps
    print(f"   true NEW links per test snapshot {test_steps[0]}..{test_steps[-1]}: {[len(wb.truth(s)) for s in test_steps]}")
    if cfg.hub_cap == 0 and info["nodes"] > 5000:
        print("   WARNING: big graph and --hub-cap is off -> may be very slow. Try  --hub-cap 300")

    # ---- Phase 4: classical static baselines
    print(f"== Phase 3-4: static baselines on snapshots {test_steps[0]}..{test_steps[-1]}")
    static_rows = []
    for name, m in (("Common Neighbors", "cn"), ("Jaccard", "jaccard"),
                    ("Adamic-Adar", "aa"), ("Preferential Attachment", "pa")):
        r = wb.run(name, wb.static_predictor(m), test_steps, wb.direct_store(), cfg.repeats)
        static_rows.append(r)
        print(f"   {name:24s} AUC={r['roc_auc']:.3f} AP={r['avg_precision']:.3f} Hits@{cfg.hits_k}={r['hits_at_k']:.3f} "
              f"P@K={r['precision']:.3f} t={r['prediction_time_s']:.2f}s")
    write_csv(f"{out}/phase4_static.csv", static_rows)

    # ---- tuning on the last 6 history snapshots only
    print(f"== Phase 5/8: tune on snapshots {wb.val_steps[0]}..{wb.val_steps[-1]} by '{cfg.tune_metric}' (no peeking at the future)")
    dyn_w, dyn_val = wb.tune_dynamic()
    lam, win, rec_val = wb.tune_recency()
    print(f"   dynamic baseline window = {dyn_w}   |   recency model: lambda = {lam}, window = {win}")
    if lam in (min(cfg.lambda_grid), max(cfg.lambda_grid)) or win in (min(cfg.recency_window_grid), max(cfg.recency_window_grid)):
        print("   NOTE: best value sits at the EDGE of the search grid -> widen the grids in config.py and re-run")
    write_csv(f"{out}/validation_recency_grid.csv", rec_val)
    write_csv(f"{out}/validation_dynamic_grid.csv", dyn_val)
    cache_size = cfg.cache_size or win

    # ---- Phase 12: experiments A-D
    print("== Phase 12: final experiments on the unseen future")
    A = wb.run("A: Static (Adamic-Adar)", wb.static_predictor("aa"), test_steps, wb.direct_store(), cfg.repeats)
    B = wb.run(f"B: Dynamic baseline (window={dyn_w})", wb.dynamic_predictor(dyn_w), test_steps,
               wb.direct_store(), cfg.repeats)
    C = wb.run(f"C: Recency-aware (lambda={lam}, window={win})", wb.recency_predictor(lam, win),
               test_steps, wb.direct_store(), cfg.repeats, save_predictions=True)
    D = wb.run(f"D: Recency + {cfg.cache_policy} cache (size={cache_size})", wb.recency_predictor(lam, win),
               test_steps, lambda: SnapshotStore(db, cache_size, cfg.cache_policy), cfg.repeats)
    final = [A, B, C, D]
    if a.with_ml:
        print("   (ML models: trained only on earlier snapshots)")
        final.append(wb.run("E: Logistic Regression, static features", wb.ml_predictor("lr", False), test_steps, wb.direct_store()))
        final.append(wb.run("F: Logistic Regression, recency features", wb.ml_predictor("lr", True, lam, win), test_steps, wb.direct_store()))
        final.append(wb.run("G: Random Forest, recency features", wb.ml_predictor("rf", True, lam, win), test_steps, wb.direct_store()))
    for r in final:
        print(f"   {r['model']:52s} AUC={r['roc_auc']:.3f} AP={r['avg_precision']:.3f} Hits@{cfg.hits_k}={r['hits_at_k']:.3f} "
              f"predict={r['prediction_time_s']:.2f}s data={r['data_access_time_s']:.3f}s hit={r['hit_rate']:.2f}")
    write_csv(f"{out}/final_results.csv", final)

    # ---- Phase 10 + 11 benchmarks
    print("== Phase 10: cache size/policy sweep")
    sweep = wb.cache_sweep(lam, win)
    write_csv(f"{out}/cache_sweep.csv", sweep)
    print("== Phase 11: index benchmark")
    idx = wb.index_benchmark()
    write_csv(f"{out}/index_benchmark.csv", idx)
    for r in idx:
        print(f"   {r['query']}: with index {r['with_index_s']*1000:.1f} ms | without {r['without_index_s']*1000:.1f} ms")

    make_plots(out, final, sweep, rec_val, idx)

    # ---- summary.md
    f3 = {"roc_auc": "{:.3f}", "avg_precision": "{:.3f}", "hits_at_k": "{:.3f}", "precision": "{:.3f}",
          "prediction_time_s": "{:.3f}", "coverage": "{:.2f}"}
    with open(f"{out}/summary.md", "w") as f:
        f.write("# SonetQ - results (auto-generated)\n\n")
        f.write(f"Dataset: **{cfg.dataset}**, users={info['nodes']}, snapshots={cfg.n_snapshots} "
                f"(history {cfg.n_history} / future {cfg.n_future}), K={cfg.k_predictions}, "
                f"Hits@{cfg.hits_k}, negatives per positive={cfg.neg_ratio}, DB backend: **{cfg.db_backend}**\n\n")
        if cfg.dataset == "synthetic":
            f.write("> **WARNING:** synthetic data is only for testing the pipeline. "
                    "Do not quote these numbers as research results.\n\n")
        cols = ["model", "roc_auc", "avg_precision", "hits_at_k", "precision", "prediction_time_s"]
        f.write("## Static baselines (unseen future snapshots)\n\n")
        f.write(md_table(static_rows, cols[:-1] + ["coverage", "prediction_time_s"], f3))
        f.write("\n`coverage` = share of true new links that were even in the candidate list.\n\n")
        f.write("## Final comparison\n\n")
        f.write(md_table(final, cols + ["data_access_time_s", "hit_rate"],
                         {**f3, "data_access_time_s": "{:.4f}", "hit_rate": "{:.2f}"}))
        f.write("\n## Cache sweep (recency model)\n\n")
        f.write(md_table(sweep, ["policy", "cache_size", "hit_rate", "data_access_time_s"],
                         {"hit_rate": "{:.2f}", "data_access_time_s": "{:.4f}"}))
        f.write("\n## Index benchmark\n\n")
        f.write(md_table(idx, ["query", "with_index_s", "without_index_s"],
                         {"with_index_s": "{:.4f}", "without_index_s": "{:.4f}"}))
        f.write("\n## Tuned on the last 6 history snapshots only\n\n")
        f.write(f"dynamic window = {dyn_w}; recency lambda = {lam}, window = {win}\n")
    db.close()
    print(f"\nDone in {time.time()-T0:.0f}s.  Open  {out}/summary.md  and the PNG plots in {out}/")


if __name__ == "__main__":
    main()
