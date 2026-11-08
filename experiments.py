"""Experiments for the blood application (all numbers come from the SYNTHETIC world)."""
import os
import random
import threading
import time
from datetime import timedelta

from sonetq.cache import SharedSnapshotStore
from sonetq.experiments import write_csv
from . import rules
from .bdb import BloodDB
from .recommender import DonorRecommender
from .scheduler import PriorityScheduler, simulate_policy


# --------------------------------------------------------------------------- ML evaluation
def evaluate_recommender(db, store, world, month, method, lam=0.5, window=6, k=5):
    """Rank donors for every request of `month` using ONLY snapshots < month; compare with the real responders."""
    rec = DonorRecommender(store, month - 1, lam, window)
    today = world["today"]
    hits = prec = recall = mrr = n = 0
    for r in world["requests"][month]:
        cands = db.eligible_donors(r["group"], r["city"], today, exclude_id=r["requester"])
        if not cands:
            continue
        top = [d for d, _ in rec.rank(r["requester"], cands, k, method)]
        found = [i for i, d in enumerate(top) if d in r["responders"]]
        hits += 1 if found else 0
        prec += len(found) / k
        recall += len(found) / len(r["responders"])
        mrr += 1.0 / (found[0] + 1) if found else 0.0
        n += 1
    p = hits / n
    return {"requests": n, f"hit@{k}": p, "hit_std_err": (p * (1 - p) / n) ** 0.5,
            f"precision@{k}": prec / n, f"recall@{k}": recall / n, "MRR": mrr / n}


def recommender_study(db, world, k=5, lam_grid=(0.0, 0.3, 0.5, 1.0, 2.0), win_grid=(3, 6, 9, 12)):
    from sonetq.cache import SnapshotStore
    store = SnapshotStore(db, capacity=12, policy="LRU")
    val_months = (10, 11, 12)
    grid = []
    for w in win_grid:
        for lam in lam_grid:
            ms = [evaluate_recommender(db, store, world, m, "recency", lam, w, k)[f"recall@{k}"] for m in val_months]
            grid.append({"window": w, "lambda": lam, "validation_recall": sum(ms) / len(ms)})
    best = max(grid, key=lambda g: g["validation_recall"])
    test_month = world["months"]
    rows = []
    for name, method in (("Random (no ML)", "random"), ("Static Adamic-Adar (all history)", "static"),
                         (f"Recency-aware (lambda={best['lambda']}, window={best['window']})", "recency")):
        res = evaluate_recommender(db, store, world, test_month, method, best["lambda"], best["window"], k)
        rows.append({"model": name, **res})
    return rows, grid, best, store


# --------------------------------------------------------------------------- OS + DBMS: threads
def threaded_processing(db_path, world, n_workers=4, aging_rate=0.01, lam=0.5, window=6, seed=1):
    """Worker threads take requests from the priority queue (OS) and allocate blood in transactions (DBMS);
    when stock is short they ask the recommender (ML) for donors.  Returns statistics."""
    today, month = world["today"], world["months"]
    main = BloodDB("sqlite", db_path)
    pending = main.pending_requests()
    now_min = max(c for _, _, c in pending)
    sched = PriorityScheduler(aging_rate, clock=lambda: float(now_min))
    for rid, pr, created in pending:                    # producer: put every request in the queue
        sched.put(rid, pr, arrival=created)
    sched.close()                                       # no more producers -> workers stop when queue is empty

    store = SharedSnapshotStore(lambda: BloodDB("sqlite", db_path), capacity=window, policy="LRU")
    rec = DonorRecommender(store, month - 1, lam, window)
    lock, order, results = threading.Lock(), [], []
    counter = [0]

    def worker(wid):
        conn = BloodDB("sqlite", db_path)               # one connection per thread
        while True:
            item = sched.get()
            if item is None:
                break
            rid, pr = item
            with lock:
                counter[0] += 1
                start_pos = counter[0]
            out = conn.allocate_units(rid, today)
            req = conn.get_request(rid)
            recs = 0
            if out["shortfall"] > 0:
                cands = conn.eligible_donors(req["blood_group"], req["city"], today, exclude_id=req["requester_id"])
                ranked = rec.rank(req["requester_id"], cands, 10, "recency")
                conn.save_notifications(rid, ranked, "recency")
                recs = len(ranked)
            with lock:
                results.append({"request_id": rid, "priority": pr, "start_pos": start_pos, "worker": wid,
                                "status": out["status"], "shortfall": out["shortfall"], "donors_recommended": recs})
        conn.close()

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    elapsed = time.perf_counter() - t0
    inv = main.check_invariants()
    summary = []
    for pr, name in rules.PRIORITY_NAMES.items():
        rs = [r for r in results if r["priority"] == pr]
        if rs:
            summary.append({"priority": name, "requests": len(rs),
                            "avg_start_position": sum(r["start_pos"] for r in rs) / len(rs),
                            "fulfilled": sum(r["status"] == "FULFILLED" for r in rs),
                            "partial": sum(r["status"] == "PARTIAL" for r in rs),
                            "unfulfilled": sum(r["status"] == "UNFULFILLED" for r in rs)})
    stats = {"workers": n_workers, "requests": len(results), "seconds": elapsed,
             "cache_hit_rate": store.hit_rate, "cache_hits": store.hits, "cache_misses": store.misses,
             "invariants": inv, "notifications": main._run("SELECT COUNT(*) FROM notifications")[0][0]}
    store.close(); main.close()
    return summary, stats, results


# --------------------------------------------------------------------------- DBMS demos
def atomicity_demo(db, world):
    """A failure in the middle of the allocation transaction must leave NO trace (ROLLBACK)."""
    today = world["today"]
    far = (today + timedelta(days=30)).isoformat()
    db.add_inventory([(1, "O+", far), (1, "O+", far)])        # make sure there IS stock to allocate
    rid = db.add_request(world["persons"][0][0], 1, "O+", "Dehradun", 2, 0, 0)
    before = db.inventory_summary(today)
    err = ""
    try:
        db.allocate_units(rid, today, fail_after_update=True)
    except RuntimeError as e:
        err = str(e)
    after = db.inventory_summary(today)
    req = db.get_request(rid)
    ok = before == after and req["units_allocated"] == 0 and req["status"] == "PENDING"
    res = db.allocate_units(rid, today)         # now the same request succeeds normally
    return {"error_raised": err, "stock_unchanged_after_failure": ok, "retry_status": res["status"]}


def constraint_demo(db):
    """The database itself refuses invalid data (CHECK / FOREIGN KEY / UNIQUE)."""
    tests = []
    def attempt(label, sql, params=()):
        try:
            db._run(sql, params); db.conn.rollback()
            tests.append({"test": label, "rejected": False})
        except Exception as e:
            db.conn.rollback()
            tests.append({"test": label, "rejected": True, "reason": type(e).__name__})
    attempt("blood group 'Z+' (CHECK)", "INSERT INTO inventory(hospital_id, blood_group, expiry_date) VALUES(1,'Z+','2026-12-01')")
    attempt("0 units requested (CHECK)", "INSERT INTO requests(requester_id,hospital_id,blood_group,city,units_needed,priority,created_at) "
                                          "VALUES(0,1,'O+','Dehradun',0,1,0)")
    attempt("unknown hospital (FOREIGN KEY)", "INSERT INTO inventory(hospital_id, blood_group, expiry_date) VALUES(999,'O+','2026-12-01')")
    attempt("priority 7 (CHECK)", "INSERT INTO requests(requester_id,hospital_id,blood_group,city,units_needed,priority,created_at) "
                                  "VALUES(0,1,'O+','Dehradun',1,7,0)")
    return tests


def big_index_benchmark(n=200_000, queries=300, seed=1):
    """Donor search 'blood group + city' on a big table, with and without the composite index."""
    import sqlite3
    rng = random.Random(seed)
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE persons(person_id INTEGER PRIMARY KEY, blood_group TEXT, city TEXT, last_donation TEXT)")
    groups, cities = list(rules.GROUPS), ["Dehradun", "Haridwar", "Roorkee", "Rishikesh", "Haldwani"]
    con.executemany("INSERT INTO persons VALUES(?,?,?,?)",
                    [(i, rng.choice(groups), rng.choice(cities), None) for i in range(n)])
    qs = [(rng.choice(groups), rng.choice(cities)) for _ in range(queries)]
    sqls = {"list matching donors (thousands of rows returned)":
                "SELECT person_id FROM persons WHERE blood_group=? AND city=? AND last_donation IS NULL",
            "count donors per group+city (dashboard query)":
                "SELECT COUNT(*) FROM persons WHERE blood_group=? AND city=?"}
    def bench(sql):
        t = time.perf_counter()
        for g, c in qs:
            con.execute(sql, (g, c) if "last_donation" in sql or True else ()).fetchall()
        return time.perf_counter() - t
    without = {k: bench(v) for k, v in sqls.items()}
    con.execute("CREATE INDEX idx_persons_group_city ON persons(blood_group, city)")
    with_idx = {k: bench(v) for k, v in sqls.items()}
    con.close()
    return [{"query": k, "rows": n, "queries": queries, "without_index_s": without[k],
             "with_index_s": with_idx[k], "speedup_x": without[k] / with_idx[k]} for k in sqls]


# --------------------------------------------------------------------------- scheduling study
def scheduling_study(aging_rates=(0.0, 0.005, 0.01, 0.02, 0.05)):
    rows = []
    for pol in ("FCFS", "PRIORITY"):
        r = simulate_policy(pol)
        rows.append({"policy": pol, "aging_rate": "-", **_flat(r)})
    for a in aging_rates[1:]:
        rows.append({"policy": "PRIORITY+AGING", "aging_rate": a, **_flat(simulate_policy("PRIORITY+AGING", aging_rate=a))})
    return rows


def _flat(r):
    return {"emergency_mean": r["EMERGENCY"]["mean"], "urgent_mean": r["URGENT"]["mean"],
            "routine_mean": r["ROUTINE"]["mean"], "routine_max": r["ROUTINE"]["max"], "overall_mean": r["ALL"]["mean"]}
