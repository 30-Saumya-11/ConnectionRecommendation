"""Link-prediction scores (Phases 3, 5, 8) + evaluation metrics.

Graph words:  node = user,  edge = connection,  N(u) = neighbours of u,  deg(u) = |N(u)|

Classical (static) scores for a NOT-yet-connected pair (u, v):
    Common Neighbours   CN  = |N(u) & N(v)|
    Jaccard                 = CN / |N(u) | N(v)|
    Adamic-Adar         AA  = sum over common neighbours z of  1 / log(deg(z))
    Preferential Attach PA  = deg(u) * deg(v)
Candidates = pairs that share at least one neighbour (2 hops apart) and are not connected yet.
hub_cap > 0 : 'friends' with more than hub_cap neighbours are ignored as middle-men (speed on huge graphs).

Dynamic baseline : AA computed on EACH snapshot separately, then averaged over last M snapshots.
Recency-aware    : every edge gets weight exp(-lambda * age); age 0 = newest snapshot.
                   Then ONE weighted Adamic-Adar pass over the merged weighted graph.
"""
import heapq
import math
from collections import defaultdict


def build_adj(edges):
    adj = defaultdict(set)
    for u, v in edges:
        if u != v:
            adj[u].add(v)
            adj[v].add(u)
    return adj


def _skip(d, hub_cap):
    return d < 2 or (hub_cap and d > hub_cap)


def static_scores(adj, seen_pairs, measure="aa", hub_cap=0):
    """measure in {'cn','jaccard','aa','pa'}.  Pairs in seen_pairs are skipped (not 'new')."""
    cn = defaultdict(int)
    aa = defaultdict(float)
    use_aa = measure == "aa"
    for z, nb in adj.items():
        d = len(nb)
        if _skip(d, hub_cap):
            continue
        w = 1.0 / math.log(d)
        nbl = sorted(nb)
        for i in range(len(nbl)):
            u = nbl[i]
            for j in range(i + 1, len(nbl)):
                p = (u, nbl[j])
                if p in seen_pairs:
                    continue
                if use_aa:
                    aa[p] += w
                else:
                    cn[p] += 1
    if measure == "cn":
        return cn
    if measure == "aa":
        return aa
    if measure == "jaccard":
        return {p: c / (len(adj[p[0]]) + len(adj[p[1]]) - c) for p, c in cn.items()}
    if measure == "pa":
        return {p: len(adj[p[0]]) * len(adj[p[1]]) for p in cn}
    raise ValueError(measure)


def dynamic_ma_scores(snapshot_edge_lists, seen_pairs, hub_cap=0):
    """Dynamic baseline: mean of per-snapshot Adamic-Adar scores over the given snapshots."""
    total = defaultdict(float)
    m = len(snapshot_edge_lists)
    for edges in snapshot_edge_lists:
        for p, s in static_scores(build_adj(edges), seen_pairs, "aa", hub_cap).items():
            total[p] += s
    return {p: s / m for p, s in total.items()}


def recency_weighted_graph(snapshot_edge_lists, lam):
    """snapshot_edge_lists must be ordered OLDEST -> NEWEST.  weight = exp(-lam * age)."""
    n = len(snapshot_edge_lists)
    w = defaultdict(lambda: defaultdict(float))
    for i, edges in enumerate(snapshot_edge_lists):
        weight = math.exp(-lam * (n - 1 - i))
        for u, v in edges:
            if u != v:
                w[u][v] += weight
                w[v][u] += weight
    return w


def weighted_aa_scores(w, seen_pairs, hub_cap=0):
    """score(u,v) = sum_z  w_uz * w_vz / log(2 + strength(z)),  strength = sum of z's weights."""
    scores = defaultdict(float)
    for z, nb in w.items():
        if _skip(len(nb), hub_cap):
            continue
        denom = math.log(2.0 + sum(nb.values()))
        items = sorted(nb.items())
        for i in range(len(items)):
            u, wu = items[i]
            for j in range(i + 1, len(items)):
                v, wv = items[j]
                p = (u, v)
                if p in seen_pairs:
                    continue
                scores[p] += wu * wv / denom
    return scores


# ---------------------------------------------------------------- features for ML models
def pair_features_static(adj, seen_pairs, hub_cap=0):
    """pair -> [CN, AA, Jaccard, log(1+PA)]"""
    cn, aa = defaultdict(int), defaultdict(float)
    for z, nb in adj.items():
        d = len(nb)
        if _skip(d, hub_cap):
            continue
        w = 1.0 / math.log(d)
        nbl = sorted(nb)
        for i in range(len(nbl)):
            for j in range(i + 1, len(nbl)):
                p = (nbl[i], nbl[j])
                if p not in seen_pairs:
                    cn[p] += 1
                    aa[p] += w
    out = {}
    for p, c in cn.items():
        du, dv = len(adj[p[0]]), len(adj[p[1]])
        out[p] = [c, aa[p], c / (du + dv - c), math.log1p(du * dv)]
    return out


def pair_features_weighted(w, seen_pairs, hub_cap=0):
    """pair -> [weighted CN, weighted AA, #common, log(1+strength_u*strength_v)]  (recency-weighted)"""
    wcn, waa, cnt = defaultdict(float), defaultdict(float), defaultdict(int)
    strength = {z: sum(nb.values()) for z, nb in w.items()}
    for z, nb in w.items():
        if _skip(len(nb), hub_cap):
            continue
        denom = math.log(2.0 + strength[z])
        items = sorted(nb.items())
        for i in range(len(items)):
            u, wu = items[i]
            for j in range(i + 1, len(items)):
                v, wv = items[j]
                p = (u, v)
                if p in seen_pairs:
                    continue
                prod = wu * wv
                wcn[p] += prod
                waa[p] += prod / denom
                cnt[p] += 1
    return {p: [wcn[p], waa[p], cnt[p], math.log1p(strength[p[0]] * strength[p[1]])] for p in wcn}


# ---------------------------------------------------------------- ranking + metrics
def top_k(scores, k):
    """Highest scores first; ties broken by node ids so results are reproducible."""
    return heapq.nlargest(k, scores.items(), key=lambda kv: (kv[1], -kv[0][0], -kv[0][1]))


def evaluate(predicted_pairs, truth, universe_size):
    """Precision / Recall / F1 at K, plus accuracy over all not-yet-connected pairs."""
    pred = set(predicted_pairs)
    tp = len(pred & truth)
    fp = len(pred) - tp
    fn = len(truth) - tp
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if tp else 0.0
    accuracy = 1.0 - (fp + fn) / universe_size if universe_size else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy, "tp": tp}


def evaluate_ranking(scores, truth, negatives, hits_k=50):
    """ROC-AUC, Average Precision and Hits@K  (the metrics of the Phase-II report).

    positives = true NEW links of the target snapshot
    negatives = sampled pairs that never become links (same sample for every method)
    A pair that a method never scored gets score 0 (= ranked at the bottom).
    Hits@K (OGB style) = share of positives scored ABOVE the K-th best negative."""
    from sklearn.metrics import roc_auc_score, average_precision_score
    pos, neg = sorted(truth), sorted(negatives)
    if not pos or not neg:
        nan = float("nan")
        return {"roc_auc": nan, "avg_precision": nan, "hits_at_k": nan}
    ps = [scores.get(p, 0.0) for p in pos]
    ns = [scores.get(p, 0.0) for p in neg]
    y = [1] * len(ps) + [0] * len(ns)
    allscores = ps + ns
    ns_sorted = sorted(ns, reverse=True)
    thr = ns_sorted[hits_k - 1] if len(ns_sorted) >= hits_k else float("-inf")
    return {"roc_auc": roc_auc_score(y, allscores),
            "avg_precision": average_precision_score(y, allscores),
            "hits_at_k": sum(1 for x in ps if x > thr) / len(ps)}


# ---------------------------------------------------------------- score ONE pair (used by the blood app)
def weighted_aa_pair(w, strength, u, v):
    """Recency-weighted Adamic-Adar score of a single pair (u, v)."""
    wu, wv = w.get(u), w.get(v)
    if not wu or not wv:
        return 0.0
    if len(wu) > len(wv):
        wu, wv = wv, wu
    total = 0.0
    for z, a in wu.items():
        b = wv.get(z)
        if b:
            total += a * b / math.log(2.0 + strength[z])
    return total


def aa_pair(adj, u, v):
    """Classical (static) Adamic-Adar score of a single pair."""
    nu, nv = adj.get(u), adj.get(v)
    if not nu or not nv:
        return 0.0
    return sum(1.0 / math.log(len(adj[z])) for z in nu & nv if len(adj[z]) > 1)
