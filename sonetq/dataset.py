"""Step 4 + 5 of the plan: get a temporal dataset and cut it into 24 snapshots.

A SNAPSHOT = all (undirected, de-duplicated) edges that were ACTIVE in one time slice.
Edges can appear in one snapshot and be absent in the next -> the network is dynamic.
"""
import random
from collections import defaultdict


# --------------------------------------------------------------------------
# 1) Real data: any SNAP-style temporal edge list  ->  "source target unix_time"
# --------------------------------------------------------------------------
def _parse_time(tok):
    try:
        return int(float(tok))
    except ValueError:
        from datetime import datetime, timezone
        tok = tok.strip().replace("T", " ").rstrip("Z")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return int(datetime.strptime(tok, fmt).replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                pass
        raise ValueError(tok)


def load_edge_list(path):
    """Reads  'source target time'  files.  Works for
       * SNAP numeric files   (CollegeMsg, email-Eu-core-temporal ...):  '1 2 1082040961'
       * TSV files WITH a header and text node names (soc-redditHyperlinks-*.tsv):
         columns are found by name (SOURCE..., TARGET..., TIME...).
       Text node names are mapped to integers.  Returns (events, id_to_name)."""
    events, ids, names = [], {}, {}
    cols = (0, 1, 2)
    first = True

    def nid(tok):
        try:
            return int(tok)
        except ValueError:
            if tok not in ids:
                ids[tok] = len(ids)
                names[ids[tok]] = tok
            return ids[tok]

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line[0] in "#%":
                continue
            parts = line.split("\t") if "\t" in line else line.replace(",", " ").split()
            if first:
                first = False
                up = [x.strip().upper() for x in parts]
                if any(x.startswith("SOURCE") for x in up):      # header row
                    si = next(i for i, x in enumerate(up) if x.startswith("SOURCE"))
                    ti = next(i for i, x in enumerate(up) if x.startswith("TARGET"))
                    tm = next(i for i, x in enumerate(up) if "TIME" in x)
                    cols = (si, ti, tm)
                    continue
            if len(parts) <= max(cols):
                continue
            try:
                events.append((nid(parts[cols[0]]), nid(parts[cols[1]]), _parse_time(parts[cols[2]])))
            except ValueError:
                continue
    if not events:
        raise ValueError(f"No usable 'source target time' rows found in {path}")
    return events, names


# --------------------------------------------------------------------------
# 2) Synthetic data: ONLY for testing that the pipeline works.
#    Do NOT draw research conclusions from it (the outcome depends on the
#    parameters we chose here).  Use a real SNAP dataset for the real results.
# --------------------------------------------------------------------------
def generate_synthetic_events(n_nodes=1000, n_snapshots=24, new_per_snapshot=600,
                              persist=0.5, drift=0.05, n_comm=10, seed=42, day=86400):
    rng = random.Random(seed)
    comm = [rng.randrange(n_comm) for _ in range(n_nodes)]
    history_adj = []
    prev_edges = set()
    events = []
    for s in range(n_snapshots):
        for n in range(n_nodes):                       # communities slowly change
            if rng.random() < drift:
                comm[n] = rng.randrange(n_comm)
        by_comm = defaultdict(list)
        for n, c in enumerate(comm):
            by_comm[c].append(n)

        edges = {e for e in prev_edges if rng.random() < persist}   # old links may repeat

        radj = defaultdict(set)                         # who talked recently (last 3 snapshots)
        for adj in history_adj[-3:]:
            for u, nb in adj.items():
                radj[u] |= nb
        active = [u for u in radj if radj[u]]

        added, tries = 0, 0
        while added < new_per_snapshot and tries < new_per_snapshot * 30:
            tries += 1
            r = rng.random()
            if r < 0.5 and active:                      # friend-of-a-friend (triadic closure)
                u = rng.choice(active)
                z = rng.choice(tuple(radj[u]))
                v = rng.choice(tuple(radj[z]))
            elif r < 0.85:                              # same community
                members = by_comm[rng.randrange(n_comm)]
                if len(members) < 2:
                    continue
                u, v = rng.sample(members, 2)
            else:                                       # random noise
                u, v = rng.randrange(n_nodes), rng.randrange(n_nodes)
            if u == v:
                continue
            e = (u, v) if u < v else (v, u)
            if e in edges:
                continue
            edges.add(e)
            added += 1

        for (u, v) in edges:
            events.append((u, v, s * day + rng.randrange(day)))
        adj = defaultdict(set)
        for u, v in edges:
            adj[u].add(v)
            adj[v].add(u)
        history_adj.append(adj)
        prev_edges = edges
    return events


# --------------------------------------------------------------------------
# 3) Cut events into n equal TIME slices
# --------------------------------------------------------------------------
def build_snapshots(events, n_snapshots=24, t_min=None, t_max=None):
    """Returns (snapshots, meta)
       snapshots[i] = {(u,v): first_timestamp}   for i = 1..n_snapshots, u < v
       meta[i]      = (start_ts, end_ts)"""
    ts = [e[2] for e in events]
    t_min = min(ts) if t_min is None else t_min
    t_max = max(ts) if t_max is None else t_max
    width = (t_max - t_min + 1) / n_snapshots
    snaps = {i: {} for i in range(1, n_snapshots + 1)}
    for u, v, t in events:
        if u == v:
            continue
        b = min(int((t - t_min) / width), n_snapshots - 1) + 1
        e = (u, v) if u < v else (v, u)
        if e not in snaps[b] or t < snaps[b][e]:
            snaps[b][e] = t
    meta = {i: (int(t_min + (i - 1) * width), int(t_min + i * width))
            for i in range(1, n_snapshots + 1)}
    return snaps, meta


def build_snapshots_monthly(events):
    """One snapshot per calendar month (UTC).  Months without any event become empty snapshots."""
    from datetime import datetime, timezone
    def month_index(t):
        d = datetime.fromtimestamp(t, timezone.utc)
        return d.year * 12 + d.month - 1
    m0 = min(month_index(e[2]) for e in events)
    m1 = max(month_index(e[2]) for e in events)
    n = m1 - m0 + 1
    snaps = {i: {} for i in range(1, n + 1)}
    for u, v, t in events:
        if u == v:
            continue
        b = month_index(t) - m0 + 1
        e = (u, v) if u < v else (v, u)
        if e not in snaps[b] or t < snaps[b][e]:
            snaps[b][e] = t
    def start_ts(i):
        m = m0 + i - 1
        return int(datetime(m // 12, m % 12 + 1, 1, tzinfo=timezone.utc).timestamp())
    meta = {i: (start_ts(i), start_ts(i + 1)) for i in range(1, n + 1)}
    return snaps, meta


def get_snapshots(cfg):
    """Returns (snapshots, meta, names).  Also sets cfg.n_snapshots / cfg.n_history."""
    names = {}
    if cfg.dataset == "file":
        events, names = load_edge_list(cfg.dataset_path)
        if cfg.snapshot_by == "month":
            snaps, meta = build_snapshots_monthly(events)
            cfg.n_snapshots = len(snaps)
        else:
            snaps, meta = build_snapshots(events, cfg.n_snapshots)
    else:
        events = generate_synthetic_events(cfg.synth_nodes, cfg.n_snapshots,
                                           cfg.synth_new_per_snapshot,
                                           drift=cfg.synth_drift, seed=cfg.seed)
        snaps, meta = build_snapshots(events, cfg.n_snapshots, t_min=0, t_max=cfg.n_snapshots * 86400 - 1)
    cfg.n_history = cfg.n_snapshots - cfg.n_future
    if cfg.n_history < 8:
        raise SystemExit(f"Only {cfg.n_snapshots} snapshots - need at least {cfg.n_future + 8}. "
                         f"Use a longer time span or --snapshot-by equal.")
    return snaps, meta, names


def describe(snapshots):
    nodes = set()
    for edges in snapshots.values():
        for u, v in edges:
            nodes.add(u)
            nodes.add(v)
    sizes = [len(snapshots[i]) for i in sorted(snapshots)]
    return {"nodes": len(nodes), "edges_per_snapshot": sizes,
            "total_snapshot_edges": sum(sizes)}
