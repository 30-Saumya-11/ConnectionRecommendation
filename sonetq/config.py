"""All settings of the project in ONE place.  Change numbers here, not in the code."""
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # ---- temporal experiment (from the action plan: 18 history + 6 future) ----
    n_snapshots: int = 24
    n_future: int = 6              # LAST 6 snapshots = unseen future  (history = n_snapshots - 6)
    n_history: int = 18            # (set automatically = n_snapshots - n_future)
    k_predictions: int = 300       # top-K pairs for Precision/Recall/F1@K
    hits_k: int = 50               # Hits@K (OGB style, against sampled negatives)
    neg_ratio: int = 5             # negatives sampled per true new link for AUC / AP / Hits@K
    tune_metric: str = "avg_precision"   # what we maximise on the validation snapshots
    hub_cap: int = 0               # skip 'friends' with more than this many neighbours (0 = off).
                                   # Use ~300 for big graphs (e.g. Reddit) to keep it fast.

    # ---- dataset ----
    dataset: str = "synthetic"     # "synthetic"  or  "file"
    dataset_path: str = "data/CollegeMsg.txt"   # used when dataset == "file"
    snapshot_by: str = "equal"     # "equal" = n_snapshots equal time slices, "month" = calendar months
    synth_nodes: int = 1000
    synth_new_per_snapshot: int = 600
    synth_drift: float = 0.05      # how fast communities change (0 = static world)
    seed: int = 42

    # ---- database ----
    db_backend: str = "sqlite"     # "sqlite" (works everywhere)  or  "mysql"
    sqlite_path: str = "results/sonetq.db"
    mysql: dict = field(default_factory=lambda: {
        "host": os.getenv("SONETQ_MYSQL_HOST", "localhost"),
        "user": os.getenv("SONETQ_MYSQL_USER", "root"),
        "password": os.getenv("SONETQ_MYSQL_PASSWORD", ""),
        "database": os.getenv("SONETQ_MYSQL_DB", "sonetq"),
    })

    # ---- model search grids (tuned ONLY on snapshots <= 18, never on 19..24) ----
    lambda_grid: tuple = (0.0, 0.1, 0.3, 0.5, 1.0)
    recency_window_grid: tuple = (4, 6, 8, 12)
    dynamic_window_grid: tuple = (2, 4, 6, 8)

    # ---- OS-inspired cache ----
    cache_size: int = 0            # 0 = "use the tuned recency window"
    cache_policy: str = "LRU"      # "LRU" or "FIFO"
    cache_sizes_to_sweep: tuple = (0, 1, 2, 4, 6, 8, 12, 24)

    repeats: int = 3               # repeat timing runs, we report the mean
    results_dir: str = "results"
