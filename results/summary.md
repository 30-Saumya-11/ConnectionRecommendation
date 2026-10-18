# SonetQ - results (auto-generated)

Dataset: **synthetic**, users=1000, snapshots=24 (history 18 / future 6), K=300, Hits@50, negatives per positive=5, DB backend: **sqlite**

> **WARNING:** synthetic data is only for testing the pipeline. Do not quote these numbers as research results.

## Static baselines (unseen future snapshots)

| model | roc_auc | avg_precision | hits_at_k | precision | coverage | prediction_time_s |
|---|---|---|---|---|---|---|
| Common Neighbors | 0.683 | 0.284 | 0.044 | 0.011 | 0.70 | 0.897 |
| Jaccard | 0.689 | 0.313 | 0.079 | 0.007 | 0.70 | 1.167 |
| Adamic-Adar | 0.689 | 0.312 | 0.082 | 0.008 | 0.70 | 0.936 |
| Preferential Attachment | 0.655 | 0.235 | 0.028 | 0.002 | 0.70 | 1.252 |

`coverage` = share of true new links that were even in the candidate list.

## Final comparison

| model | roc_auc | avg_precision | hits_at_k | precision | prediction_time_s | data_access_time_s | hit_rate |
|---|---|---|---|---|---|---|---|
| A: Static (Adamic-Adar) | 0.689 | 0.312 | 0.082 | 0.008 | 1.015 | 0.0612 | 0.00 |
| B: Dynamic baseline (window=4) | 0.640 | 0.360 | 0.291 | 0.030 | 0.092 | 0.0134 | 0.00 |
| C: Recency-aware (lambda=1.0, window=12) | 0.735 | 0.507 | 0.373 | 0.032 | 0.483 | 0.0434 | 0.00 |
| D: Recency + LRU cache (size=12) | 0.735 | 0.507 | 0.373 | 0.032 | 0.458 | 0.0115 | 0.76 |
| E: Logistic Regression, static features | 0.691 | 0.314 | 0.081 | 0.009 | 16.560 | 0.2423 | 0.00 |
| F: Logistic Regression, recency features | 0.733 | 0.503 | 0.348 | 0.041 | 10.367 | 0.2544 | 0.00 |
| G: Random Forest, recency features | 0.733 | 0.513 | 0.371 | 0.044 | 22.026 | 0.2361 | 0.00 |

## Cache sweep (recency model)

| policy | cache_size | hit_rate | data_access_time_s |
|---|---|---|---|
| LRU | 0 | 0.00 | 0.0441 |
| LRU | 1 | 0.00 | 0.0420 |
| LRU | 2 | 0.00 | 0.0437 |
| LRU | 4 | 0.00 | 0.0472 |
| LRU | 6 | 0.00 | 0.0458 |
| LRU | 8 | 0.00 | 0.0482 |
| LRU | 12 | 0.76 | 0.0102 |
| LRU | 24 | 0.76 | 0.0115 |
| FIFO | 0 | 0.00 | 0.0502 |
| FIFO | 1 | 0.00 | 0.0483 |
| FIFO | 2 | 0.00 | 0.0487 |
| FIFO | 4 | 0.00 | 0.0466 |
| FIFO | 6 | 0.00 | 0.0498 |
| FIFO | 8 | 0.00 | 0.0470 |
| FIFO | 12 | 0.76 | 0.0111 |
| FIFO | 24 | 0.76 | 0.0106 |

## Index benchmark

| query | with_index_s | without_index_s |
|---|---|---|
| all 24 snapshots (by snapshot_id) | 0.0119 | 0.0332 |
| edges of 300 random users (by source/target) | 0.0150 | 0.4553 |

## Tuned on the last 6 history snapshots only

dynamic window = 4; recency lambda = 1.0, window = 12
