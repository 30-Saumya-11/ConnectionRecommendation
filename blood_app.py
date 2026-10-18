"""Blood donor recommendation application (built on the SonetQ engine).
    python blood_app.py all      run every experiment, write results/blood/*
    python blood_app.py web      start the small web page  ->  http://localhost:8000
"""
import os
import sys
import time

from sonetq.db import SnapshotDB
from sonetq.experiments import write_csv
from sonetq.reporting import md_table
from bloodapp import experiments as ex, rules
from bloodapp.bdb import BloodDB
from bloodapp.world import build_world, load_world_into_db, insert_future_requests

OUT = "results/blood"
DB_PATH = f"{OUT}/blood.db"


def make_db(world, path=DB_PATH, with_future_requests=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    db = BloodDB("sqlite", path)
    load_world_into_db(db, world)
    ids = insert_future_requests(db, world, world["months"]) if with_future_requests else []
    return db, ids


def run_all():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    print("== building the synthetic world and the database")
    world = build_world()
    db, ids = make_db(world)
    print(f"   people={len(world['persons'])}  history snapshots={world['months']-1}  pending requests={len(ids)}")

    print("== ML: donor ranking (tuned on months 10-12, tested on month 13)")
    rec_rows, grid, best, store = ex.recommender_study(db, world)
    for r in rec_rows:
        print("  ", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
    write_csv(f"{OUT}/recommender_results.csv", rec_rows)
    write_csv(f"{OUT}/recommender_tuning.csv", grid)
    print(f"   best lambda={best['lambda']}, window={best['window']}  (if at the edge of the grid -> widen it)")
    print(f"   snapshot-cache hit rate during evaluation: {store.hit_rate:.2f}")

    print("== OS: scheduling policies (simulation)")
    sched_rows = ex.scheduling_study()
    for r in sched_rows:
        print(f"   {r['policy']:15s} aging={r['aging_rate']!s:6s} emergency={r['emergency_mean']:6.1f}  routine={r['routine_mean']:6.1f}  routine-max={r['routine_max']:6.1f}")
    write_csv(f"{OUT}/scheduling_study.csv", sched_rows)

    print("== OS + DBMS: 4 worker threads, priority queue, atomic allocation")
    db.close()
    summary, stats, results = ex.threaded_processing(DB_PATH, world, n_workers=4)
    for r in summary:
        print("  ", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()})
    print(f"   {stats['requests']} requests in {stats['seconds']:.2f}s | cache hit rate {stats['cache_hit_rate']:.2f} "
          f"| invariants {stats['invariants']} | donor notifications {stats['notifications']}")
    write_csv(f"{OUT}/threaded_summary.csv", summary)
    write_csv(f"{OUT}/threaded_requests.csv", results)

    print("== DBMS: atomicity, constraints, index")
    db = BloodDB("sqlite", DB_PATH)
    atom = ex.atomicity_demo(db, world)
    cons = ex.constraint_demo(db)
    idx = ex.big_index_benchmark()
    print("  ", atom)
    for c in cons:
        print("  ", c)
    for r in idx:
        print("  ", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    write_csv(f"{OUT}/constraint_demo.csv", cons)
    write_csv(f"{OUT}/index_benchmark_big.csv", idx)
    db.close()

    f = {"hit@5": "{:.2f}", "hit_std_err": "{:.3f}", "precision@5": "{:.3f}", "recall@5": "{:.2f}", "MRR": "{:.3f}"}
    with open(f"{OUT}/blood_summary.md", "w") as fh:
        fh.write("# Blood donor application - results (auto-generated)\n\n")
        fh.write("> **WARNING:** all data is SYNTHETIC. These numbers show that the system works, not that it will "
                 "perform like this on real people.\n\n")
        fh.write("## ML: donor ranking (month 13 = unseen future)\n\n")
        fh.write(md_table(rec_rows, ["model", "requests", "hit@5", "hit_std_err", "precision@5", "recall@5", "MRR"], f))
        fh.write(f"\nTuned on months 10-12: lambda={best['lambda']}, window={best['window']}\n\n")
        fh.write("## OS: scheduling policies (minutes of waiting)\n\n")
        fh.write(md_table(sched_rows, ["policy", "aging_rate", "emergency_mean", "urgent_mean", "routine_mean", "routine_max", "overall_mean"],
                          {k: "{:.1f}" for k in ("emergency_mean", "urgent_mean", "routine_mean", "routine_max", "overall_mean")}))
        fh.write("\n## OS + DBMS: threaded processing\n\n")
        fh.write(md_table(summary, ["priority", "requests", "avg_start_position", "fulfilled", "partial", "unfulfilled"],
                          {"avg_start_position": "{:.1f}"}))
        fh.write(f"\nWorkers={stats['workers']}, time={stats['seconds']:.2f}s, cache hit rate={stats['cache_hit_rate']:.2f}, "
                 f"database invariants (all must be 0): {stats['invariants']}\n\n")
        fh.write("## DBMS demos\n\n")
        fh.write(f"Atomicity: {atom}\n\n")
        fh.write(md_table([{"test": c['test'], "rejected": str(c['rejected']), "reason": c.get('reason', '')} for c in cons],
                          ["test", "rejected", "reason"]))
        fh.write("\n" + md_table(idx, ["query", "rows", "queries", "without_index_s", "with_index_s", "speedup_x"],
                                 {"without_index_s": "{:.3f}", "with_index_s": "{:.3f}", "speedup_x": "{:.0f}"}))
    print(f"\nDone in {time.time()-t0:.0f}s -> {OUT}/blood_summary.md")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "all":
        run_all()
    elif cmd == "web":
        from bloodapp.webapp import serve
        serve()
    else:
        print(__doc__)
