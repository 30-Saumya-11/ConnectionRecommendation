# Blood donor application - results (auto-generated)

> **WARNING:** all data is SYNTHETIC. These numbers show that the system works, not that it will perform like this on real people.

## ML: donor ranking (month 13 = unseen future)

| model | requests | hit@5 | hit_std_err | precision@5 | recall@5 | MRR |
|---|---|---|---|---|---|---|
| Random (no ML) | 100 | 0.22 | 0.041 | 0.062 | 0.10 | 0.121 |
| Static Adamic-Adar (all history) | 100 | 0.36 | 0.048 | 0.108 | 0.17 | 0.247 |
| Recency-aware (lambda=0.5, window=9) | 100 | 0.74 | 0.044 | 0.206 | 0.31 | 0.480 |

Tuned on months 10-12: lambda=0.5, window=9

## OS: scheduling policies (minutes of waiting)

| policy | aging_rate | emergency_mean | urgent_mean | routine_mean | routine_max | overall_mean |
|---|---|---|---|---|---|---|
| FCFS | - | 52.5 | 53.1 | 57.0 | 284.1 | 55.4 |
| PRIORITY | - | 4.8 | 7.1 | 87.7 | 426.2 | 55.3 |
| PRIORITY+AGING | 0.005 | 4.8 | 14.5 | 83.8 | 367.9 | 55.2 |
| PRIORITY+AGING | 0.01 | 9.0 | 25.3 | 77.8 | 321.5 | 55.2 |
| PRIORITY+AGING | 0.02 | 18.6 | 36.1 | 70.5 | 299.7 | 54.9 |
| PRIORITY+AGING | 0.05 | 33.2 | 45.8 | 63.4 | 278.6 | 55.1 |

## OS + DBMS: threaded processing

| priority | requests | avg_start_position | fulfilled | partial | unfulfilled |
|---|---|---|---|---|---|
| EMERGENCY | 6 | 3.7 | 4 | 0 | 2 |
| URGENT | 28 | 21.7 | 27 | 0 | 1 |
| ROUTINE | 66 | 67.0 | 17 | 2 | 47 |

Workers=4, time=0.37s, cache hit rate=0.98, database invariants (all must be 0): {'units_allocated_twice': 0, 'request_count_mismatch': 0, 'over_allocated_requests': 0, 'allocated_units_without_row': 0}

## DBMS demos

Atomicity: {'error_raised': 'injected failure (to demonstrate ROLLBACK)', 'stock_unchanged_after_failure': True, 'retry_status': 'FULFILLED'}

| test | rejected | reason |
|---|---|---|
| blood group 'Z+' (CHECK) | True | IntegrityError |
| 0 units requested (CHECK) | True | IntegrityError |
| unknown hospital (FOREIGN KEY) | True | IntegrityError |
| priority 7 (CHECK) | True | IntegrityError |

| query | rows | queries | without_index_s | with_index_s | speedup_x |
|---|---|---|---|---|---|
| list matching donors (thousands of rows returned) | 200000 | 300 | 3.952 | 1.072 | 4 |
| count donors per group+city (dashboard query) | 200000 | 300 | 3.201 | 0.055 | 58 |
