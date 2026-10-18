"""Run:  python -m unittest discover -s tests -v"""
import os, sys, tempfile, threading, unittest
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bloodapp import rules, scheduler as sc
from bloodapp.bdb import BloodDB
from bloodapp.recommender import DonorRecommender
from bloodapp.world import build_world, load_world_into_db
from bloodapp import experiments as ex
from sonetq.cache import SnapshotStore

TODAY = date(2026, 10, 14)


def tiny_db(path=":memory:"):
    db = BloodDB("sqlite", path)
    db.create_schema(); db.create_blood_schema()
    db.add_hospitals([(1, "H1", "Dehradun")])
    db.add_persons([(1, "A", "O+", "Dehradun", 1990, None, 1), (2, "B", "A+", "Dehradun", 1990, None, 1)])
    db.create_blood_indexes()
    return db


class TestRules(unittest.TestCase):
    def test_compatibility(self):
        self.assertEqual(set(rules.compatible_donor_groups("O-")), {"O-"})
        self.assertEqual(set(rules.compatible_donor_groups("A-")), {"O-", "A-"})
        self.assertEqual(set(rules.compatible_donor_groups("AB+")), set(rules.GROUPS))
        self.assertFalse(rules.can_donate_to("A+", "O+"))
        self.assertFalse(rules.can_donate_to("O+", "O-"))

    def test_eligibility(self):
        ok = lambda by, last, av=1: rules.is_eligible(by, last, av, TODAY)[0]
        self.assertTrue(ok(1990, None))
        self.assertFalse(ok(1990, (TODAY - timedelta(days=30)).isoformat()))
        self.assertTrue(ok(1990, (TODAY - timedelta(days=120)).isoformat()))
        self.assertFalse(ok(2012, None))
        self.assertFalse(ok(1950, None))
        self.assertFalse(ok(1990, None, 0))

    def test_sql_filter_matches_python_rules(self):
        w = build_world(n_people=300, months=5, requests_per_month=5, new_social=80)
        db = BloodDB("sqlite", ":memory:"); load_world_into_db(db, w)
        for g in ("O+", "AB-", "A+"):
            sql = set(db.eligible_donors(g, "Dehradun", w["today"]))
            py = {p[0] for p in w["persons"] if p[3] == "Dehradun" and p[2] in rules.compatible_donor_groups(g)
                  and p[0] in w["eligible"]}
            self.assertEqual(sql, py)


class TestScheduler(unittest.TestCase):
    def test_priority_order_and_aging(self):
        s = sc.PriorityScheduler(aging_rate=0.0, clock=lambda: 100.0)
        s.put(1, 2, arrival=0); s.put(2, 0, arrival=50); s.put(3, 1, arrival=10); s.close()
        self.assertEqual([s.get()[0] for _ in range(3)], [2, 3, 1])
        s = sc.PriorityScheduler(aging_rate=0.05, clock=lambda: 100.0)
        s.put(1, 2, arrival=0); s.put(2, 0, arrival=99); s.close()
        self.assertEqual(s.get()[0], 1)

    def test_blocking_queue_with_threads(self):
        s = sc.PriorityScheduler(); got, lock = [], threading.Lock()
        def worker():
            while True:
                it = s.get()
                if it is None: return
                with lock: got.append(it[0])
        ts = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in ts]
        for i in range(200): s.put(i, i % 3)
        s.close(); [t.join() for t in ts]
        self.assertEqual(sorted(got), list(range(200)))

    def test_starvation_and_aging_in_simulation(self):
        fcfs, prio, aged = (sc.simulate_policy(p, n_jobs=3000) for p in ("FCFS", "PRIORITY", "PRIORITY+AGING"))
        self.assertLess(prio["EMERGENCY"]["mean"], fcfs["EMERGENCY"]["mean"] / 3)
        self.assertGreater(prio["ROUTINE"]["max"], fcfs["ROUTINE"]["max"])
        self.assertLess(aged["ROUTINE"]["max"], prio["ROUTINE"]["max"])


class TestDatabase(unittest.TestCase):
    def test_allocation_prefers_exact_group_then_soonest_expiry(self):
        db = tiny_db()
        db.add_inventory([(1, "O-", "2026-11-01"), (1, "A+", "2026-11-20"), (1, "A+", "2026-10-20"), (1, "A+", "2026-10-01")])
        rid = db.add_request(2, 1, "A+", "Dehradun", 2, 1, 0)
        res = db.allocate_units(rid, TODAY)
        self.assertEqual(res["status"], "FULFILLED")
        used = db._run("SELECT blood_group, expiry_date FROM inventory WHERE status='ALLOCATED' ORDER BY expiry_date")
        self.assertEqual(used, [("A+", "2026-10-20"), ("A+", "2026-11-20")])
        self.assertEqual(db.check_invariants(), {k: 0 for k in db.check_invariants()})

    def test_partial_and_rollback(self):
        db = tiny_db()
        db.add_inventory([(1, "A+", "2026-11-20")])
        rid = db.add_request(2, 1, "A+", "Dehradun", 3, 1, 0)
        self.assertEqual(db.allocate_units(rid, TODAY)["status"], "PARTIAL")
        rid2 = db.add_request(2, 1, "A+", "Dehradun", 1, 1, 0)
        db.add_inventory([(1, "A+", "2026-11-25")])
        with self.assertRaises(RuntimeError):
            db.allocate_units(rid2, TODAY, fail_after_update=True)
        self.assertEqual(db.get_request(rid2)["status"], "PENDING")
        self.assertEqual(db._run("SELECT COUNT(*) FROM inventory WHERE status='AVAILABLE'")[0][0], 1)

    def test_constraints(self):
        w = build_world(n_people=100, months=4, requests_per_month=3, new_social=30)
        db = BloodDB("sqlite", ":memory:"); load_world_into_db(db, w)
        self.assertTrue(all(c["rejected"] for c in ex.constraint_demo(db)))

    def test_concurrent_allocation_never_double_books(self):
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        db = tiny_db(path)
        db.add_inventory([(1, "O+", "2026-12-01")] * 30)
        ids = [db.add_request(2, 1, "O+", "Dehradun", 3, i % 3, i) for i in range(20)]
        def worker(chunk):
            c = BloodDB("sqlite", path)
            for rid in chunk: c.allocate_units(rid, TODAY)
            c.close()
        ts = [threading.Thread(target=worker, args=(ids[i::4],)) for i in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
        inv = db.check_invariants()
        self.assertEqual(inv, {k: 0 for k in inv})
        self.assertEqual(db._run("SELECT COUNT(*) FROM allocations")[0][0], 30)


class TestRecommender(unittest.TestCase):
    def test_recent_contact_beats_old_contact(self):
        class Fake:
            def get(self, i):
                return {1: [(1, 50), (50, 10)], 2: [], 3: [(1, 60), (60, 11)]}[i]
        rec = DonorRecommender(Fake(), 3, lam=1.0, window=3)
        self.assertEqual(rec.rank(1, [10, 11], k=2, method="recency")[0][0], 11)
        st = rec.rank(1, [10, 11], k=2, method="static")
        self.assertAlmostEqual(st[0][1], st[1][1])

    def test_ranking_uses_only_past_snapshots(self):
        w = build_world(n_people=400, months=6, requests_per_month=10, new_social=120)
        db = BloodDB("sqlite", ":memory:"); load_world_into_db(db, w)
        self.assertEqual(db._run("SELECT MAX(snapshot_id) FROM snapshots")[0][0], 5)
        store = SnapshotStore(db, 5)
        r = ex.evaluate_recommender(db, store, w, 6, "recency", 0.5, 3, 5)
        self.assertGreater(r["requests"], 0)
        self.assertTrue(all(i <= 5 for i in store.cached_ids()))


if __name__ == "__main__":
    unittest.main()
