"""Run:  python -m unittest discover -s tests -v"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sonetq import linkpred as lp, dataset as ds
from sonetq.cache import SnapshotStore
from sonetq.db import SnapshotDB
from sonetq.config import Config
from sonetq.experiments import Workbench
import math


class FakeDB:
    def __init__(self): self.calls = []
    def get_snapshot_edges(self, sid): self.calls.append(sid); return [(sid, sid + 1)]


class TestScores(unittest.TestCase):
    def setUp(self):                      # path 1-2-3 plus 2-4 : candidates (1,3) (1,4) (3,4)
        self.adj = lp.build_adj([(1, 2), (2, 3), (2, 4)])

    def test_cn_jaccard_pa_aa(self):
        seen = {(1, 2), (2, 3), (2, 4)}
        self.assertEqual(lp.static_scores(self.adj, seen, "cn")[(1, 3)], 1)
        self.assertAlmostEqual(lp.static_scores(self.adj, seen, "jaccard")[(1, 3)], 1.0)
        self.assertEqual(lp.static_scores(self.adj, seen, "pa")[(1, 3)], 1)
        self.assertAlmostEqual(lp.static_scores(self.adj, seen, "aa")[(1, 3)], 1 / math.log(3))

    def test_seen_pairs_are_skipped(self):
        seen = {(1, 2), (2, 3), (2, 4), (1, 3)}
        self.assertNotIn((1, 3), lp.static_scores(self.adj, seen, "cn"))

    def test_recency_prefers_new_edges(self):
        old = [(1, 2), (2, 3)]            # old triangle-ish path -> candidate (1,3)
        new = [(5, 6), (6, 7)]            # new path -> candidate (5,7)
        w = lp.recency_weighted_graph([old, new], lam=1.0)
        sc = lp.weighted_aa_scores(w, set())
        self.assertGreater(sc[(5, 7)], sc[(1, 3)])
        w0 = lp.recency_weighted_graph([old, new], lam=0.0)   # lambda 0 = no preference
        sc0 = lp.weighted_aa_scores(w0, set())
        self.assertAlmostEqual(sc0[(5, 7)], sc0[(1, 3)])

    def test_metrics(self):
        m = lp.evaluate([(1, 2), (3, 4)], {(1, 2), (5, 6)}, 100)
        self.assertAlmostEqual(m["precision"], 0.5)
        self.assertAlmostEqual(m["recall"], 0.5)
        self.assertAlmostEqual(m["f1"], 0.5)


class TestCache(unittest.TestCase):
    def test_lru_vs_fifo(self):
        for policy, expect_evicted in (("LRU", 2), ("FIFO", 1)):
            db = FakeDB(); st = SnapshotStore(db, 2, policy)
            for sid in (1, 2, 1, 3):      # 1 is touched again before 3 arrives
                st.get(sid)
            self.assertNotIn(expect_evicted, st.cached_ids())

    def test_hit_miss_counts_and_no_cache(self):
        db = FakeDB(); st = SnapshotStore(db, 2, "LRU")
        for sid in (1, 1, 2, 2, 1): st.get(sid)
        self.assertEqual((st.hits, st.misses), (3, 2))
        db2 = FakeDB(); st0 = SnapshotStore(db2, 0)
        for sid in (1, 1, 1): st0.get(sid)
        self.assertEqual(db2.calls, [1, 1, 1])       # capacity 0 -> always the database


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(synth_nodes=150, synth_new_per_snapshot=60, k_predictions=30, repeats=1)
        self.snaps, self.meta, self.names = ds.get_snapshots(self.cfg)
        self.db = SnapshotDB("sqlite", ":memory:")
        self.db.create_schema(); self.db.load(self.snaps, self.meta); self.db.create_indexes()
        self.wb = Workbench(self.snaps, self.db, self.cfg)

    def test_db_roundtrip(self):
        for sid in (1, 10, 24):
            self.assertEqual({tuple(sorted(e)) for e in self.db.get_snapshot_edges(sid)}, set(self.snaps[sid]))

    def test_24_snapshots(self):
        self.assertEqual(len(self.snaps), 24)

    def test_no_future_leakage(self):
        for s in self.wb.test_steps:
            truth, seen = self.wb.truth(s), self.wb.seen_pairs[s - 1]
            self.assertFalse(truth & seen)                                   # truth is really 'new'
            self.assertFalse(any(e in self.wb.edge_sets[j] for j in range(s, 25) for e in seen - self.wb.seen_pairs[s - 1]))
            self.assertEqual(self.wb.seen_pairs[s - 1], set().union(*[self.wb.edge_sets[i] for i in range(1, s)]))

    def test_cache_does_not_change_predictions(self):
        pred = self.wb.recency_predictor(0.5, 4)
        a = self.wb.run("c", pred, self.wb.test_steps, self.wb.direct_store())
        b = self.wb.run("d", pred, self.wb.test_steps, lambda: SnapshotStore(self.db, 4, "LRU"))
        self.assertAlmostEqual(a["f1"], b["f1"])
        self.assertGreater(b["hit_rate"], 0)

    def test_file_loader(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("# comment\n1 2 100\n2 3 5000\n3 4 9999\n1 2 100\n")
        ev, _ = ds.load_edge_list(f.name); os.remove(f.name)
        self.assertEqual(len(ev), 4)
        snaps, _ = ds.build_snapshots(ev, 3)
        self.assertEqual([len(snaps[i]) for i in (1, 2, 3)], [1, 1, 1])


class TestMetricsAndLoader(unittest.TestCase):
    def test_ranking_metrics_perfect_and_hits(self):
        truth = {(1, 2), (3, 4)}
        negs = {(5, 6), (7, 8), (9, 10)}
        scores = {(1, 2): 0.9, (3, 4): 0.8, (5, 6): 0.1}
        m = lp.evaluate_ranking(scores, truth, negs, hits_k=1)
        self.assertAlmostEqual(m["roc_auc"], 1.0)
        self.assertAlmostEqual(m["avg_precision"], 1.0)
        self.assertAlmostEqual(m["hits_at_k"], 1.0)      # both positives beat the best negative (0.1)
        m2 = lp.evaluate_ranking({(5, 6): 0.9, (1, 2): 0.5}, truth, negs, hits_k=1)
        self.assertAlmostEqual(m2["hits_at_k"], 0.0)     # best negative 0.9 beats every positive

    def test_reddit_style_tsv_with_header_and_text_names(self):
        rows = ["SOURCE_SUBREDDIT\tTARGET_SUBREDDIT\tPOST_ID\tTIMESTAMP\tLINK_SENTIMENT",
                "askreddit\tfunny\tp1\t2014-01-05 10:00:00\t1",
                "funny\tpics\tp2\t2014-02-07 11:00:00\t-1",
                "pics\taskreddit\tp3\t2014-04-01 00:00:01\t1"]
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as f:
            f.write("\n".join(rows) + "\n")
        ev, names = ds.load_edge_list(f.name); os.remove(f.name)
        self.assertEqual(len(ev), 3)
        self.assertEqual(set(names.values()), {"askreddit", "funny", "pics"})
        snaps, meta = ds.build_snapshots_monthly(ev)
        self.assertEqual(len(snaps), 4)                  # Jan, Feb, Mar(empty), Apr
        self.assertEqual([len(snaps[i]) for i in (1, 2, 3, 4)], [1, 1, 0, 1])

    def test_ml_predictor_runs_and_uses_only_past(self):
        cfg = Config(synth_nodes=150, synth_new_per_snapshot=60, k_predictions=30, repeats=1)
        snaps, meta, names = ds.get_snapshots(cfg)
        db = SnapshotDB("sqlite", ":memory:"); db.create_schema(); db.load(snaps, meta, names)
        wb = Workbench(snaps, db, cfg)
        r = wb.run("ml", wb.ml_predictor("lr", True, 0.5, 4), wb.test_steps, wb.direct_store())
        self.assertGreater(r["roc_auc"], 0.0)


if __name__ == "__main__":
    unittest.main()
