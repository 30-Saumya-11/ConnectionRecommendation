"""The temporal experiment (Phases 4, 6, 9, 10, 12) + benchmarks.

Protocol (fixed for ALL methods, no future leakage):
    predict snapshot s (the last n_future snapshots) using ONLY snapshots 1..s-1
    TRUE new links  = pairs active in snapshot s, never connected in 1..s-1,
                      whose two users both already exist in 1..s-1
    NEGATIVES       = random pairs of existing users that never become links (same for all methods)
    Methods may read snapshots ONLY through SnapshotStore (database / cache).
"""
import csv
import math
import os
import random
from time import perf_counter

from . import linkpred as lp
from .cache import SnapshotStore

METRICS = ("precision", "recall", "f1", "accuracy", "roc_auc", "avg_precision", "hits_at_k", "coverage")


class Workbench:
    def __init__(self, snapshots, db, cfg):
        self.cfg, self.db = cfg, db
        self.n = cfg.n_snapshots
        self.edge_sets = {i: set(snapshots[i]) for i in snapshots}
        self.seen_pairs, self.seen_nodes = [set()], [set()]
        for s in range(1, self.n + 1):
            self.seen_pairs.append(self.seen_pairs[-1] | self.edge_sets[s])
            self.seen_nodes.append(self.seen_nodes[-1] | {x for e in self.edge_sets[s] for x in e})
        self.val_steps = list(range(cfg.n_history - 5, cfg.n_history + 1))   # last 6 history snapshots
        self.test_steps = list(range(cfg.n_history + 1, self.n + 1))          # the unseen future
        self._neg = {}

    def truth(self, s):
        sp, sn = self.seen_pairs[s - 1], self.seen_nodes[s - 1]
        return {e for e in self.edge_sets[s] if e not in sp and e[0] in sn and e[1] in sn}

    def universe(self, s):
        n = len(self.seen_nodes[s - 1])
        return n * (n - 1) // 2 - len(self.seen_pairs[s - 1])

    def negatives(self, s):
        if s in self._neg:
            return self._neg[s]
        truth, sp = self.truth(s), self.seen_pairs[s - 1]
        nodes = sorted(self.seen_nodes[s - 1])
        want = max(self.cfg.neg_ratio * len(truth), 200)
        rng, out, tries = random.Random(self.cfg.seed * 1000 + s), set(), 0
        while len(nodes) > 1 and len(out) < want and tries < want * 50:
            tries += 1
            u, v = rng.sample(nodes, 2)
            e = (u, v) if u < v else (v, u)
            if e not in sp and e not in truth:
                out.add(e)
        self._neg[s] = out
        return out

    # ------------------------------------------------------------ predictors
    # signature of every predictor:  fn(store, s, seen_pairs) -> {pair: score}
    # => ANY model of yours (GNN, XGBoost, ...) can be plugged in the same way.
    def static_predictor(self, measure):
        cap = self.cfg.hub_cap
        def fn(store, s, seen):
            adj = lp.build_adj(e for i in range(1, s) for e in store.get(i))
            return lp.static_scores(adj, seen, measure, cap)
        return fn

    def dynamic_predictor(self, window):
        cap = self.cfg.hub_cap
        def fn(store, s, seen):
            lists = [store.get(i) for i in range(max(1, s - window), s)]
            return lp.dynamic_ma_scores(lists, seen, cap)
        return fn

    def recency_predictor(self, lam, window):
        cap = self.cfg.hub_cap
        def fn(store, s, seen):
            lists = [store.get(i) for i in range(max(1, s - window), s)]
            return lp.weighted_aa_scores(lp.recency_weighted_graph(lists, lam), seen, cap)
        return fn

    # ---- ML models (optional): train ONLY on earlier steps, then score step s
    def _features(self, store, t, recency, lam, window):
        seen, cap = self.seen_pairs[t - 1], self.cfg.hub_cap
        if recency:
            lists = [store.get(i) for i in range(max(1, t - window), t)]
            return lp.pair_features_weighted(lp.recency_weighted_graph(lists, lam), seen, cap)
        adj = lp.build_adj(e for i in range(1, t) for e in store.get(i))
        return lp.pair_features_static(adj, seen, cap)

    def ml_predictor(self, kind="lr", recency=False, lam=0.5, window=6, train_steps=3):
        def fn(store, s, seen):
            from sklearn.linear_model import LogisticRegression
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            rng = random.Random(self.cfg.seed + s)
            X, y = [], []
            for t in range(max(3, s - train_steps), s):          # labels come from snapshots < s only
                feats, truth = self._features(store, t, recency, lam, window), self.truth(t)
                pos = [p for p in feats if p in truth]
                negs = [p for p in feats if p not in truth]
                rng.shuffle(negs)
                for p in pos + negs[:max(20 * len(pos), 200)]:
                    X.append(feats[p]); y.append(1 if p in truth else 0)
            if sum(y) == 0 or sum(y) == len(y):
                return {}
            if kind == "rf":
                model = RandomForestClassifier(n_estimators=100, max_depth=8, n_jobs=1,
                                               class_weight="balanced_subsample", random_state=self.cfg.seed)
            else:
                model = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=500))
            model.fit(X, y)
            cand = self._features(store, s, recency, lam, window)
            if not cand:
                return {}
            pairs = list(cand)
            probs = model.predict_proba([cand[p] for p in pairs])[:, 1]
            return dict(zip(pairs, probs))
        return fn

    # ------------------------------------------------------------ one experiment
    def run(self, name, predictor, steps, store_factory, repeats=1, save_predictions=False):
        k = self.cfg.k_predictions
        per_step, runs = [], []
        for r in range(repeats):
            store = store_factory()
            pred_time = 0.0
            for s in steps:
                seen = self.seen_pairs[s - 1]
                t0, a0 = perf_counter(), store.access_time
                scores = predictor(store, s, seen)
                top = lp.top_k(scores, k)
                elapsed = perf_counter() - t0
                pred_time += elapsed - (store.access_time - a0)
                if r == 0:
                    truth = self.truth(s)
                    m = lp.evaluate([p for p, _ in top], truth, self.universe(s))
                    m.update(lp.evaluate_ranking(scores, truth, self.negatives(s), self.cfg.hits_k))
                    m.update(step=s, truth_size=len(truth),
                             coverage=len(truth & set(scores)) / len(truth) if truth else float("nan"))
                    per_step.append(m)
                    if save_predictions:
                        self.db.save_predictions(name, s, [(u, v, sc) for (u, v), sc in top])
            runs.append((pred_time, store.access_time, store.hits, store.misses, store.requests))

        def mean(key):
            vals = [m[key] for m in per_step if not math.isnan(m[key])]
            return sum(vals) / len(vals) if vals else float("nan")

        n = len(runs)
        out = {"model": name}
        for key in METRICS:
            out[key] = mean(key)
        out.update({
            "prediction_time_s": sum(x[0] for x in runs) / n,
            "data_access_time_s": sum(x[1] for x in runs) / n,
            "cache_hits": runs[0][2], "cache_misses": runs[0][3], "requests": runs[0][4],
            "hit_rate": runs[0][2] / runs[0][4] if runs[0][4] else 0.0,
        })
        return out

    def direct_store(self):
        return lambda: SnapshotStore(self.db, 0)

    # ------------------------------------------------------------ tuning (no leakage!)
    def tune_dynamic(self):
        rows, key = [], self.cfg.tune_metric
        for w in self.cfg.dynamic_window_grid:
            r = self.run(f"dyn_w{w}", self.dynamic_predictor(w), self.val_steps, self.direct_store())
            rows.append({"window": w, "score": r[key], "f1": r["f1"]})
        return max(rows, key=lambda x: x["score"])["window"], rows

    def tune_recency(self):
        rows, key = [], self.cfg.tune_metric
        for w in self.cfg.recency_window_grid:
            for lam in self.cfg.lambda_grid:
                r = self.run("val", self.recency_predictor(lam, w), self.val_steps, self.direct_store())
                rows.append({"window": w, "lambda": lam, "score": r[key], "f1": r["f1"]})
        best = max(rows, key=lambda x: x["score"])
        return best["lambda"], best["window"], rows

    # ------------------------------------------------------------ cache sweep (Phase 10)
    def cache_sweep(self, lam, window):
        rows = []
        for policy in ("LRU", "FIFO"):
            for size in self.cfg.cache_sizes_to_sweep:
                r = self.run(f"{policy}_{size}", self.recency_predictor(lam, window), self.test_steps,
                             lambda size=size, policy=policy: SnapshotStore(self.db, size, policy),
                             repeats=self.cfg.repeats)
                rows.append({"policy": policy, "cache_size": size, "hit_rate": r["hit_rate"],
                             "hits": r["cache_hits"], "misses": r["cache_misses"],
                             "data_access_time_s": r["data_access_time_s"],
                             "prediction_time_s": r["prediction_time_s"]})
        return rows

    # ------------------------------------------------------------ index benchmark (Step 22)
    def index_benchmark(self, rounds=5, node_samples=300):
        rng = random.Random(1)
        nodes = rng.sample(sorted(self.seen_nodes[-1]), min(node_samples, len(self.seen_nodes[-1])))

        def bench():
            t = perf_counter()
            for _ in range(rounds):
                for s in range(1, self.n + 1):
                    self.db.get_snapshot_edges(s)
            t_snap = perf_counter() - t
            t = perf_counter()
            for u in nodes:
                self.db.get_node_edges(u)
            return t_snap / rounds, perf_counter() - t

        self.db.create_indexes()
        with_idx = bench()
        self.db.drop_indexes()
        without = bench()
        self.db.create_indexes()
        return [
            {"query": f"all {self.n} snapshots (by snapshot_id)", "with_index_s": with_idx[0], "without_index_s": without[0]},
            {"query": f"edges of {len(nodes)} random users (by source/target)", "with_index_s": with_idx[1],
             "without_index_s": without[1]},
        ]


def write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
