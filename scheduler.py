"""OS part 1: PRIORITY SCHEDULING with AGING  (+ a thread-safe producer-consumer queue).

Priority: 0 EMERGENCY  <  1 URGENT  <  2 ROUTINE        (smaller number = served first)
Aging   : effective_priority = base_priority - aging_rate * minutes_waited
          -> a routine request that waits long slowly becomes as important as a fresh emergency,
             so it can never STARVE (the classic problem of pure priority scheduling).
"""
import heapq
import random
import threading
import time

BASE = {0: 0.0, 1: 1.0, 2: 2.0}


def effective_priority(priority, waited_minutes, aging_rate):
    return BASE[priority] - aging_rate * waited_minutes


class PriorityScheduler:
    """Many producers call put(); worker threads call get().  A Condition variable (OS synchronisation)
    makes workers sleep while the queue is empty and wakes them when work arrives."""

    def __init__(self, aging_rate=0.02, clock=None):
        self.aging_rate = aging_rate
        self.clock = clock or (lambda: time.monotonic() / 60.0)      # minutes
        self._items, self._seq, self._closed = [], 0, False
        self._cv = threading.Condition()

    def put(self, request_id, priority, arrival=None):
        with self._cv:
            self._seq += 1
            self._items.append((priority, self.clock() if arrival is None else arrival, self._seq, request_id))
            self._cv.notify()

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def get(self):
        """Blocks until a job exists.  Returns (request_id, priority) or None when closed and empty."""
        with self._cv:
            while not self._items and not self._closed:
                self._cv.wait()
            if not self._items:
                return None
            now = self.clock()
            best = min(self._items, key=lambda it: (effective_priority(it[0], now - it[1], self.aging_rate), it[1], it[2]))
            self._items.remove(best)
            return best[3], best[0]

    def __len__(self):
        with self._cv:
            return len(self._items)


# ----------------------------------------------------------------------------------------
# Discrete-event simulation to COMPARE policies (pure maths, deterministic with a seed)
# ----------------------------------------------------------------------------------------
def simulate_policy(policy, n_jobs=4000, n_workers=2, load=0.97, mean_service=10.0,
                    mix=(0.10, 0.30, 0.60), aging_rate=0.02, seed=1):
    """policy in {'FCFS','PRIORITY','PRIORITY+AGING'}.  Times are in minutes."""
    rng = random.Random(seed)
    lam = load * n_workers / mean_service
    t, jobs = 0.0, []
    for i in range(n_jobs):
        t += rng.expovariate(lam)
        pr = rng.choices((0, 1, 2), weights=mix)[0]
        jobs.append((t, pr, rng.expovariate(1.0 / mean_service), i))
    free = [0.0] * n_workers
    heapq.heapify(free)
    pending, idx = [], 0
    waits = {0: [], 1: [], 2: []}
    while idx < n_jobs or pending:
        now = heapq.heappop(free)
        while idx < n_jobs and jobs[idx][0] <= now:
            pending.append(jobs[idx]); idx += 1
        if not pending:
            now = jobs[idx][0]; pending.append(jobs[idx]); idx += 1
        if policy == "FCFS":
            key = lambda j: (j[0],)
        elif policy == "PRIORITY":
            key = lambda j: (j[1], j[0])
        else:
            key = lambda j: (effective_priority(j[1], now - j[0], aging_rate), j[0])
        job = min(pending, key=key)
        pending.remove(job)
        waits[job[1]].append(now - job[0])
        heapq.heappush(free, now + job[2])
    out = {}
    for pr, name in ((0, "EMERGENCY"), (1, "URGENT"), (2, "ROUTINE")):
        w = sorted(waits[pr])
        out[name] = {"mean": sum(w) / len(w), "p95": w[int(0.95 * (len(w) - 1))], "max": w[-1], "n": len(w)}
    allw = [x for v in waits.values() for x in v]
    out["ALL"] = {"mean": sum(allw) / len(allw), "p95": sorted(allw)[int(0.95 * (len(allw) - 1))], "max": max(allw), "n": len(allw)}
    return out
