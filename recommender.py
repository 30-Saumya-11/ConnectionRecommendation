"""ML part: rank eligible donors for a request with LINK PREDICTION on the social graph.

Graph  : persons = nodes;  social ties AND earlier 'X helped Y' donations = edges, one snapshot per month.
Idea   : a donor who is (recently) well connected to the requester through common contacts is a more
         likely 'future link' = more likely to respond.   Recent months count more (recency decay).
Medical rules are applied BEFORE ranking (bdb.eligible_donors), ML only orders the survivors.
All snapshots are read through the SnapshotStore -> the OS-inspired cache is used on every request.
"""
import random

from sonetq import linkpred as lp


class DonorRecommender:
    def __init__(self, store, latest_snapshot, lam=0.5, window=6):
        self.store, self.latest, self.lam, self.window = store, latest_snapshot, lam, window

    def _recency_graph(self):
        lists = [self.store.get(i) for i in range(max(1, self.latest - self.window + 1), self.latest + 1)]
        w = lp.recency_weighted_graph(lists, self.lam)
        return w, {z: sum(nb.values()) for z, nb in w.items()}

    def rank(self, requester, candidates, k=10, method="recency"):
        """Returns [(donor_id, score)] best first.  method: 'recency' | 'static' | 'random'"""
        if method == "random":
            rng = random.Random(requester)
            c = sorted(candidates)
            rng.shuffle(c)
            return [(d, 0.0) for d in c[:k]]
        if method == "static":                                  # classic Adamic-Adar on ALL history
            adj = lp.build_adj(e for i in range(1, self.latest + 1) for e in self.store.get(i))
            scored = [(d, lp.aa_pair(adj, requester, d)) for d in candidates]
        else:
            w, strength = self._recency_graph()
            scored = [(d, lp.weighted_aa_pair(w, strength, requester, d)) for d in candidates]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]
