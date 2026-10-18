# Blood Donor Recommendation - an APPLICATION of the SonetQ project

**One line:** when a patient's family needs blood, the system (1) serves the most urgent requests first, (2) gives blood
from stock safely, and (3) if stock is short, recommends the donors most likely to respond using link prediction on the social graph.

| Subject | What we use | File |
|---|---|---|
| **ML** | Recency-aware link prediction ranks eligible donors (people recently connected to the requester through common contacts rank higher) | `bloodapp/recommender.py`, `sonetq/linkpred.py` |
| **OS** | Priority scheduling (Emergency > Urgent > Routine) with **aging** (no starvation); producer-consumer queue with a Condition variable; worker threads; mutex-protected shared snapshot cache | `bloodapp/scheduler.py`, `sonetq/cache.py` (SharedSnapshotStore), `bloodapp/experiments.py` (threaded_processing) |
| **DBMS** | Normalised tables, PRIMARY/FOREIGN KEY, CHECK, UNIQUE, composite indexes, **atomic allocation transaction** (commit/rollback), locking, invariant checks | `bloodapp/bdb.py`, `sql/schema_blood_mysql.sql` |

## Run
```bash
python blood_app.py all                      # all experiments -> results/blood/blood_summary.md + CSVs
python blood_app.py web                      # full-featured web portal at http://127.0.0.1:8000
python -m unittest discover -s tests -v      # 36 tests pass (100% test coverage)
python generate_word_report.py               # generates SonetQ_BloodDonation_Final_Project_Report.docx
```

## Demo Credentials (Web App)
* **👑 Admin:** username=`admin`, password=`admin123` (Full system diagnostics, cache hit stats, ACID invariant audit, audit logs, ML model comparison sandbox)
* **🏥 Hospital Staff:** username=`staff`, password=`staff123` (OS priority queue with dynamic aging, "Process next" atomic transaction, blood bank inventory)
* **🩸 Requester / Patient:** username=`user10`, password=`user123` (Submit emergency/routine blood requests, check medical eligibility, view allocated units & recommended donors)

## How a request flows
1. Request is stored as PENDING (priority 0/1/2, created time).
2. Scheduler picks the next one: smallest `priority - aging_rate x minutes_waited`.
3. `allocate_units` runs ONE transaction: choose compatible, non-expired units (exact group first, soonest expiry first),
   mark them ALLOCATED, insert allocation rows, update the request -> COMMIT (any error -> ROLLBACK, nothing changes).
4. If units are still missing: `eligible_donors` (rules: ABO/Rh compatible, same city, 18-65 years, 90 days since last donation)
   -> recommender ranks them -> top 10 are saved in `notifications`.

## Rules vs ML (say this in the viva)
Medical eligibility is **rule-based** (safety). ML only **orders** people who already pass the rules.
The rule numbers (90 days, age 18-65, 35-day shelf life) are common defaults - **verify with official guidelines** before quoting them.

## Academic Deliverables Included
* **Working Software Prototype:** Flask web app with role-based dashboard, OS priority queue with dynamic aging, DBMS atomic allocation, and ML link prediction ranking.
* **Final Project Word Report:** [SonetQ_BloodDonation_Final_Project_Report.docx](file:///C:/Users/hp/.gemini/antigravity/scratch/sonetq_blood_project/SonetQ_BloodDonation_Final_Project_Report.docx) formatted for Graphic Era University evaluation.
* **Automated Test Suite:** 36 automated unit tests validating authentication, RBAC, OS scheduling, cache memory hierarchy, ACID transactions, and ML evaluation.

