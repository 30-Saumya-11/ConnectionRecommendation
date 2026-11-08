"""DBMS part: schema, constraints, indexes and the ATOMIC allocation transaction.

Tables (3NF-style):  persons, hospitals, requests, inventory, allocations, notifications
            (+ the SonetQ tables snapshots / nodes / edges that hold the social graph)
Concepts shown: PRIMARY/FOREIGN KEY, CHECK, UNIQUE, indexes, transactions (ACID),
                row locking (BEGIN IMMEDIATE in SQLite / SELECT ... FOR UPDATE in MySQL).
"""
from datetime import timedelta

from sonetq.db import SnapshotDB
from . import rules

GROUP_CHECK = "('A+','A-','B+','B-','AB+','AB-','O+','O-')"


class BloodDB(SnapshotDB):
    def __init__(self, backend="sqlite", sqlite_path=":memory:", mysql_cfg=None):
        super().__init__(backend, sqlite_path, mysql_cfg)
        if backend == "sqlite":
            self._run("PRAGMA foreign_keys = ON")           # make SQLite enforce FOREIGN KEYs
            if sqlite_path != ":memory:":
                self._run("PRAGMA journal_mode = WAL")      # readers and a writer can work together

    # ------------------------------------------------------------------ schema
    def create_blood_schema(self):
        pk = "INT AUTO_INCREMENT PRIMARY KEY" if self.backend == "mysql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for t in ("notifications", "allocations", "inventory", "requests", "persons", "hospitals"):
            self._run(f"DROP TABLE IF EXISTS {t}")
        self._run("CREATE TABLE hospitals(hospital_id INT PRIMARY KEY, name VARCHAR(80) NOT NULL, city VARCHAR(40) NOT NULL)")
        self._run(f"""CREATE TABLE persons(
            person_id BIGINT PRIMARY KEY, name VARCHAR(80) NOT NULL,
            blood_group VARCHAR(3) NOT NULL CHECK (blood_group IN {GROUP_CHECK}),
            city VARCHAR(40) NOT NULL, birth_year INT NOT NULL,
            last_donation DATE NULL, available TINYINT NOT NULL DEFAULT 1)""")
        self._run(f"""CREATE TABLE requests(
            request_id {pk}, requester_id BIGINT NOT NULL, hospital_id INT NOT NULL,
            blood_group VARCHAR(3) NOT NULL CHECK (blood_group IN {GROUP_CHECK}),
            city VARCHAR(40) NOT NULL,
            units_needed INT NOT NULL CHECK (units_needed > 0), units_allocated INT NOT NULL DEFAULT 0,
            priority INT NOT NULL CHECK (priority IN (0,1,2)),
            status VARCHAR(12) NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','FULFILLED','PARTIAL','UNFULFILLED')),
            created_at INT NOT NULL,
            FOREIGN KEY (requester_id) REFERENCES persons(person_id),
            FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id))""")
        self._run(f"""CREATE TABLE inventory(
            unit_id {pk}, hospital_id INT NOT NULL,
            blood_group VARCHAR(3) NOT NULL CHECK (blood_group IN {GROUP_CHECK}),
            expiry_date DATE NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE','ALLOCATED','EXPIRED')),
            request_id INT NULL,
            FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id),
            FOREIGN KEY (request_id) REFERENCES requests(request_id))""")
        self._run(f"""CREATE TABLE allocations(
            alloc_id {pk}, request_id INT NOT NULL, unit_id INT NOT NULL UNIQUE, allocated_on DATE NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests(request_id),
            FOREIGN KEY (unit_id) REFERENCES inventory(unit_id))""")
        self._run(f"""CREATE TABLE notifications(
            notif_id {pk}, request_id INT NOT NULL, donor_id BIGINT NOT NULL,
            rank_no INT NOT NULL, score DOUBLE NOT NULL, model VARCHAR(30) NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests(request_id),
            FOREIGN KEY (donor_id) REFERENCES persons(person_id))""")
        self.conn.commit()

    BLOOD_INDEXES = {
        "idx_persons_group_city": "persons(blood_group, city)",
        "idx_inventory_lookup": "inventory(status, blood_group, expiry_date)",
        "idx_requests_status": "requests(status, priority)",
    }

    def create_blood_indexes(self):
        for name, target in self.BLOOD_INDEXES.items():
            try:
                self._run(f"CREATE INDEX {name} ON {target}")
            except Exception:
                pass
        self.conn.commit()

    # ------------------------------------------------------------------ inserts
    def add_hospitals(self, rows):
        self._many(f"INSERT INTO hospitals VALUES({self.ph},{self.ph},{self.ph})", rows)
        self.conn.commit()

    def add_persons(self, rows):
        ph = self.ph
        self._many(f"INSERT INTO persons VALUES({','.join([ph] * 7)})", rows)
        self.conn.commit()

    def add_inventory(self, rows):
        """rows = (hospital_id, blood_group, expiry_date)"""
        ph = self.ph
        self._many(f"INSERT INTO inventory(hospital_id, blood_group, expiry_date) VALUES({ph},{ph},{ph})", rows)
        self.conn.commit()

    def add_request(self, requester_id, hospital_id, blood_group, city, units, priority, created_at):
        ph = self.ph
        cur = self.conn.cursor()
        cur.execute(f"INSERT INTO requests(requester_id, hospital_id, blood_group, city, units_needed, priority, created_at) "
                    f"VALUES({','.join([ph] * 7)})",
                    (requester_id, hospital_id, blood_group, city, units, priority, created_at))
        rid = cur.lastrowid
        cur.close()
        self.conn.commit()
        return rid

    # ------------------------------------------------------------------ reads
    def get_request(self, rid):
        r = self._run(f"SELECT request_id, requester_id, hospital_id, blood_group, city, units_needed, "
                      f"units_allocated, priority, status, created_at FROM requests WHERE request_id={self.ph}", (rid,))
        if not r:
            return None
        keys = ("request_id", "requester_id", "hospital_id", "blood_group", "city", "units_needed",
                "units_allocated", "priority", "status", "created_at")
        return dict(zip(keys, r[0]))

    def pending_requests(self):
        return self._run("SELECT request_id, priority, created_at FROM requests WHERE status='PENDING' "
                         "ORDER BY created_at, request_id")

    def eligible_donors(self, recipient_group, city, today, exclude_id=None, gap_days=rules.MIN_GAP_DAYS):
        """Rule-based filter done INSIDE the database (uses idx_persons_group_city)."""
        ph = self.ph
        groups = rules.compatible_donor_groups(recipient_group)
        cutoff = (today - timedelta(days=gap_days)).isoformat()
        rows = self._run(
            f"SELECT person_id FROM persons WHERE blood_group IN ({','.join([ph] * len(groups))}) AND city={ph} "
            f"AND available=1 AND (last_donation IS NULL OR last_donation <= {ph}) "
            f"AND birth_year <= {ph} AND birth_year >= {ph}",
            (*groups, city, cutoff, today.year - rules.MIN_AGE, today.year - rules.MAX_AGE))
        return [r[0] for r in rows if r[0] != exclude_id]

    def inventory_summary(self, today):
        rows = self._run(f"SELECT blood_group, COUNT(*) FROM inventory WHERE status='AVAILABLE' AND expiry_date >= {self.ph} "
                         f"GROUP BY blood_group", (today.isoformat(),))
        d = dict(rows)
        return {g: d.get(g, 0) for g in rules.GROUPS}

    def expire_units(self, today):
        self._run(f"UPDATE inventory SET status='EXPIRED' WHERE status='AVAILABLE' AND expiry_date < {self.ph}",
                  (today.isoformat(),))
        self.conn.commit()

    # ------------------------------------------------------------------ THE transaction
    def allocate_units(self, request_id, today, fail_after_update=False):
        """ATOMIC: either every step below happens, or none of it (rollback).
        1 read the request   2 pick compatible, non-expired units (exact group first, soonest expiry first)
        3 mark units ALLOCATED   4 insert allocation rows   5 update the request   -> COMMIT.
        The WHERE status='AVAILABLE' check + UNIQUE(unit_id) + the lock make a double allocation impossible."""
        ph, today_s = self.ph, today.isoformat()
        lock = " FOR UPDATE" if self.backend == "mysql" else ""
        cur = self.conn.cursor()
        try:
            if self.backend == "sqlite":
                cur.execute("BEGIN IMMEDIATE")                       # take the write lock now
            cur.execute(f"SELECT blood_group, units_needed, units_allocated FROM requests WHERE request_id={ph}{lock}",
                        (request_id,))
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"request {request_id} not found")
            group, needed, have = row
            remaining = needed - have
            got = 0
            if remaining > 0:
                groups = rules.compatible_donor_groups(group)
                cur.execute(
                    f"SELECT unit_id FROM inventory WHERE status='AVAILABLE' AND expiry_date >= {ph} "
                    f"AND blood_group IN ({','.join([ph] * len(groups))}) "
                    f"ORDER BY CASE WHEN blood_group={ph} THEN 0 ELSE 1 END, expiry_date, unit_id LIMIT {int(remaining)}{lock}",
                    (today_s, *groups, group))
                for (uid,) in cur.fetchall():
                    cur.execute(f"UPDATE inventory SET status='ALLOCATED', request_id={ph} "
                                f"WHERE unit_id={ph} AND status='AVAILABLE'", (request_id, uid))
                    if cur.rowcount != 1:
                        continue
                    cur.execute(f"INSERT INTO allocations(request_id, unit_id, allocated_on) VALUES({ph},{ph},{ph})",
                                (request_id, uid, today_s))
                    got += 1
            if fail_after_update and got:
                raise RuntimeError("injected failure (to demonstrate ROLLBACK)")
            total = have + got
            status = "FULFILLED" if total >= needed else ("PARTIAL" if total > 0 else "UNFULFILLED")
            cur.execute(f"UPDATE requests SET units_allocated={ph}, status={ph} WHERE request_id={ph}",
                        (total, status, request_id))
            self.conn.commit()
            return {"request_id": request_id, "status": status, "allocated_now": got,
                    "total": total, "needed": needed, "shortfall": max(0, needed - total)}
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def save_notifications(self, request_id, ranked, model):
        ph = self.ph
        self._many(f"INSERT INTO notifications(request_id, donor_id, rank_no, score, model) VALUES({ph},{ph},{ph},{ph},{ph})",
                   [(request_id, int(d), i + 1, float(s), model) for i, (d, s) in enumerate(ranked)])
        self.conn.commit()

    def check_invariants(self):
        """All numbers must be 0 for a consistent database."""
        q = lambda sql: self._run(sql)[0][0]
        return {
            "units_allocated_twice": q("SELECT COUNT(*) FROM (SELECT unit_id FROM allocations GROUP BY unit_id HAVING COUNT(*) > 1) t"),
            "request_count_mismatch": q("SELECT COUNT(*) FROM requests r WHERE r.units_allocated != "
                                        "(SELECT COUNT(*) FROM allocations a WHERE a.request_id = r.request_id)"),
            "over_allocated_requests": q("SELECT COUNT(*) FROM requests WHERE units_allocated > units_needed"),
            "allocated_units_without_row": q("SELECT COUNT(*) FROM inventory i WHERE i.status='ALLOCATED' AND NOT EXISTS "
                                             "(SELECT 1 FROM allocations a WHERE a.unit_id = i.unit_id)"),
        }
