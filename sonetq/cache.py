"""OS-inspired snapshot cache (Phase 10).

IMPORTANT (say this in the viva): this is an APPLICATION-LEVEL cache that borrows
ideas from OS memory management.  We do NOT modify the operating system.

    OS idea                      ->  our project
    ---------------------------      -----------------------------------------
    RAM frame / page             ->  one cached snapshot
    page fault                   ->  cache MISS  (go to the database = "disk")
    page hit                     ->  cache HIT   (use the copy in memory)
    page-replacement (LRU/FIFO)  ->  which snapshot to throw out when full
    temporal locality            ->  recent snapshots are needed again and again
"""
import threading
from collections import OrderedDict
from time import perf_counter


class SnapshotStore:
    """The ONLY way the models read snapshots.  capacity=0  ==  no cache (always the DB)."""

    def __init__(self, db, capacity=0, policy="LRU"):
        if policy not in ("LRU", "FIFO"):
            raise ValueError("policy must be LRU or FIFO")
        self.db, self.capacity, self.policy = db, capacity, policy
        self._cache = OrderedDict()
        self.hits = self.misses = self.requests = 0
        self.access_time = 0.0            # seconds spent fetching snapshots

    def get(self, snapshot_id):
        t0 = perf_counter()
        self.requests += 1
        if self.capacity > 0 and snapshot_id in self._cache:
            self.hits += 1
            if self.policy == "LRU":
                self._cache.move_to_end(snapshot_id)       # mark as recently used
            edges = self._cache[snapshot_id]
        else:
            self.misses += 1
            edges = self._fetch(snapshot_id)               # slow path: database
            if self.capacity > 0:
                self._cache[snapshot_id] = edges
                if len(self._cache) > self.capacity:
                    self._cache.popitem(last=False)         # evict front (LRU victim / oldest)
        self.access_time += perf_counter() - t0
        return edges

    def _fetch(self, snapshot_id):
        return self.db.get_snapshot_edges(snapshot_id)

    @property
    def hit_rate(self):
        return self.hits / self.requests if self.requests else 0.0

    @property
    def miss_rate(self):
        return self.misses / self.requests if self.requests else 0.0

    def cached_ids(self):
        return list(self._cache.keys())


class SharedSnapshotStore(SnapshotStore):
    """Same cache, but safe for MANY THREADS (OS idea: a mutex protects the shared cache).
    Every thread uses its own database connection (thread-local)."""

    def __init__(self, db_factory, capacity=0, policy="LRU"):
        super().__init__(None, capacity, policy)
        self._lock = threading.Lock()
        self._factory = db_factory
        self._local = threading.local()
        self._conns = []

    def _fetch(self, snapshot_id):
        if not hasattr(self._local, "db"):
            self._local.db = self._factory()
            self._conns.append(self._local.db)
        return self._local.db.get_snapshot_edges(snapshot_id)

    def get(self, snapshot_id):
        with self._lock:                      # critical section
            return super().get(snapshot_id)

    def close(self):
        for c in self._conns:
            try:
                c.close()
            except Exception:
                pass
