"""A SYNTHETIC world for the prototype (real donor data is private and not available).

!!! Because we invented how people behave, the numbers computed on this world only prove that the
!!! system WORKS - they are not scientific evidence.  Replace with real/anonymised data for real claims.

People live in cities, have blood groups, and form social ties month after month.
From month 3 on, blood requests happen; responders are drawn from eligible, compatible donors of the
same city and are more likely to be people socially close to the requester in the LAST 3 MONTHS.
'X helped Y' becomes an edge in that month's snapshot.  Months 1..12 are history, month 13 is the future.
"""
import random
from collections import defaultdict
from datetime import date, timedelta

from . import rules

CITIES = ["Dehradun", "Haridwar", "Roorkee", "Rishikesh", "Haldwani"]
GROUP_WEIGHTS = {"O+": 0.36, "B+": 0.30, "A+": 0.22, "AB+": 0.07, "O-": 0.02, "B-": 0.01, "A-": 0.015, "AB-": 0.005}  # rough, synthetic
TODAY = date(2026, 10, 14)


def build_world(seed=7, n_people=1500, months=13, new_social=600, requests_per_month=100):
    rng = random.Random(seed)
    groups, weights = zip(*GROUP_WEIGHTS.items())
    persons = []
    for pid in range(n_people):
        g = rng.choices(groups, weights)[0]
        city = CITIES[pid % len(CITIES)]
        birth = rng.randint(TODAY.year - 68, TODAY.year - 18)
        r = rng.random()
        last = None if r < 0.45 else (TODAY - timedelta(days=rng.randint(20, 90))).isoformat() if r < 0.70 \
            else (TODAY - timedelta(days=rng.randint(91, 500))).isoformat()
        avail = 1 if rng.random() < 0.92 else 0
        persons.append((pid, f"Person {pid}", g, city, birth, last, avail))
    P = {p[0]: p for p in persons}
    by_city = defaultdict(list)
    for p in persons:
        by_city[p[3]].append(p[0])
    eligible = {p[0] for p in persons if rules.is_eligible(p[4], p[5], p[6], TODAY)[0]}

    pool_cache = {}
    def pool(city, group):
        key = (city, group)
        if key not in pool_cache:
            ok = set(rules.compatible_donor_groups(group))
            pool_cache[key] = [d for d in by_city[city] if d in eligible and P[d][2] in ok]
        return pool_cache[key]

    month_edges, month_adj = {}, {}
    prev_social, requests = set(), defaultdict(list)
    for m in range(1, months + 1):
        social = {e for e in prev_social if rng.random() < 0.5}
        radj = defaultdict(set)
        for mm in range(max(1, m - 3), m):
            for u, nb in month_adj[mm].items():
                radj[u] |= nb
        active = [u for u in radj if radj[u]]
        added = tries = 0
        while added < new_social and tries < new_social * 30:
            tries += 1
            x = rng.random()
            if x < 0.5 and active:
                u = rng.choice(active); z = rng.choice(tuple(radj[u])); v = rng.choice(tuple(radj[z]))
            elif x < 0.9:
                u, v = rng.sample(by_city[rng.choice(CITIES)], 2)
            else:
                u, v = rng.randrange(n_people), rng.randrange(n_people)
            if u == v:
                continue
            e = (u, v) if u < v else (v, u)
            if e not in social:
                social.add(e); added += 1
        edges = set(social)

        # recency-weighted contacts of the last 3 months (this is the hidden 'human behaviour' of the world)
        wadj = defaultdict(lambda: defaultdict(float))
        for age, mm in enumerate(range(m - 1, max(0, m - 4), -1)):
            for u, nb in month_adj[mm].items():
                for v in nb:
                    wadj[u][v] += 1.0 / (age + 1)
        if m >= 3:
            for _ in range(requests_per_month):
                r_id = rng.randrange(n_people)
                group, city = P[r_id][2], P[r_id][3]
                cands = [d for d in pool(city, group) if d != r_id]
                if len(cands) < 3:
                    continue
                wr = wadj.get(r_id, {})
                weights_c = []
                for d in cands:
                    wd = wadj.get(d, {})
                    prox = sum(a * wd.get(z, 0.0) for z, a in wr.items()) + 2.0 * wr.get(d, 0.0)
                    weights_c.append(1.0 + 15.0 * prox)
                k = min(len(cands), rng.choice((2, 3, 3, 4, 5)))
                chosen = set()
                while len(chosen) < k:
                    chosen.add(rng.choices(cands, weights_c)[0])
                for d in chosen:
                    edges.add((r_id, d) if r_id < d else (d, r_id))
                requests[m].append({"requester": r_id, "group": group, "city": city,
                                    "units": rng.choice((1, 1, 2, 2, 3)),
                                    "priority": rng.choices((0, 1, 2), (0.10, 0.30, 0.60))[0],
                                    "responders": chosen})
        adj = defaultdict(set)
        for u, v in edges:
            adj[u].add(v); adj[v].add(u)
        month_edges[m], month_adj[m], prev_social = edges, adj, social
    return {"persons": persons, "month_edges": month_edges, "requests": requests,
            "months": months, "today": TODAY, "eligible": eligible}



def load_world_into_db(db, world, hospitals_stock=20, seed=3):
    """Creates every table, loads people, hospitals, inventory and the social snapshots 1..months-1."""
    rng = random.Random(seed)
    db.create_schema()                       # snapshots / nodes / edges / predictions (SonetQ)
    db.create_blood_schema()
    hist = world["months"] - 1
    snaps = {m: {e: m * 2_592_000 + 1 for e in world["month_edges"][m]} for m in range(1, hist + 1)}
    meta = {m: (m * 2_592_000, (m + 1) * 2_592_000) for m in range(1, hist + 1)}
    db.add_hospitals([(i + 1, f"{c} Blood Bank", c) for i, c in enumerate(CITIES)])
    db.add_persons(world["persons"])
    db.load(snaps, meta, {p[0]: p[1] for p in world["persons"]})
    inv = []
    groups, weights = zip(*GROUP_WEIGHTS.items())
    for h in range(1, len(CITIES) + 1):
        for _ in range(hospitals_stock):
            g = rng.choices(groups, weights)[0]
            exp = world["today"] + timedelta(days=rng.randint(-5, rules.RBC_SHELF_LIFE_DAYS))
            inv.append((h, g, exp.isoformat()))
    db.add_inventory(inv)
    db.create_indexes()
    db.create_blood_indexes()
    return hist


def insert_future_requests(db, world, month, window_minutes=120, seed=5):
    """Month-13 requests of the world become PENDING requests in the database."""
    rng = random.Random(seed)
    ids = []
    for r in world["requests"][month]:
        hid = CITIES.index(r["city"]) + 1
        ids.append(db.add_request(r["requester"], hid, r["group"], r["city"], r["units"],
                                  r["priority"], rng.randrange(window_minutes)))
    return ids
