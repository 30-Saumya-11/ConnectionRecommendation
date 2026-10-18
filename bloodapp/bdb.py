"""DBMS part: schema, constraints, indexes and the ATOMIC allocation transaction.

Tables (3NF-style):  persons, hospitals, requests, inventory, allocations, notifications
            (+ the SonetQ tables snapshots / nodes / edges that hold the social graph)
Concepts shown: PRIMARY/FOREIGN KEY, CHECK, UNIQUE, indexes, transactions (ACID),
                row locking (BEGIN IMMEDIATE in SQLite / SELECT ... FOR UPDATE in MySQL).
"""
from datetime import timedelta
import hashlib
import secrets

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
        for t in ("audit_logs", "users", "notifications", "allocations", "inventory", "requests", "persons", "hospitals"):
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
        self._run(f"""CREATE TABLE users(
            user_id {pk}, username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(128) NOT NULL, salt VARCHAR(64) NOT NULL,
            role VARCHAR(20) NOT NULL CHECK (role IN ('ADMIN','STAFF','USER','DONOR')),
            person_id BIGINT NULL, created_at INT NOT NULL,
            FOREIGN KEY (person_id) REFERENCES persons(person_id))""")
        self._run(f"""CREATE TABLE audit_logs(
            log_id {pk}, username VARCHAR(50) NOT NULL,
            role VARCHAR(20) NOT NULL, action VARCHAR(50) NOT NULL,
            details TEXT NOT NULL, created_at INT NOT NULL)""")
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

    # ------------------------------------------------------------------ Authentication & Audit
    @staticmethod
    def hash_password(password, salt=None):
        if salt is None:
            salt = secrets.token_hex(16)
        pwd_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return pwd_hash, salt

    def register_user(self, username, password, role="USER", person_id=None, created_at=0):
        username = username.strip().lower()
        if not username or not password:
            raise ValueError("Username and password cannot be empty")
        if role not in ("ADMIN", "STAFF", "USER", "DONOR"):
            raise ValueError(f"Invalid role: {role}")
        ph = self.ph
        pwd_hash, salt = self.hash_password(password)
        cur = self.conn.cursor()
        cur.execute(f"INSERT INTO users(username, password_hash, salt, role, person_id, created_at) "
                    f"VALUES({','.join([ph] * 6)})",
                    (username, pwd_hash, salt, role, person_id, created_at))
        uid = cur.lastrowid
        cur.close()
        self.conn.commit()
        return uid

    def add_person(self, name, blood_group, city, birth_year, last_donation=None, available=1):
        ph = self.ph
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(MAX(person_id), 0) + 1 FROM persons")
        pid = cur.fetchone()[0]
        cur.execute(f"INSERT INTO persons(person_id, name, blood_group, city, birth_year, last_donation, available) "
                    f"VALUES({','.join([ph] * 7)})",
                    (pid, name, blood_group, city, birth_year, last_donation, available))
        cur.close()
        self.conn.commit()
        return pid

    def verify_user(self, username, password):
        username = username.strip().lower()
        ph = self.ph
        rows = self._run(f"SELECT user_id, username, password_hash, salt, role, person_id FROM users WHERE username={ph}", (username,))
        if not rows:
            return None
        uid, uname, stored_hash, salt, role, pid = rows[0]
        check_hash, _ = self.hash_password(password, salt)
        if check_hash == stored_hash:
            profile = None
            if pid:
                p_rows = self._run(f"SELECT name, blood_group, city, birth_year, last_donation, available FROM persons WHERE person_id={ph}", (pid,))
                if p_rows:
                    profile = {
                        "name": p_rows[0][0],
                        "blood_group": p_rows[0][1],
                        "city": p_rows[0][2],
                        "birth_year": p_rows[0][3],
                        "last_donation": p_rows[0][4],
                        "available": p_rows[0][5]
                    }
            return {"user_id": uid, "username": uname, "role": role, "person_id": pid, "profile": profile}
        return None

    def log_audit(self, username, role, action, details, created_at=0):
        ph = self.ph
        self._run(f"INSERT INTO audit_logs(username, role, action, details, created_at) VALUES({','.join([ph] * 5)})",
                  (username, role, action, str(details), created_at))
        self.conn.commit()

    def get_audit_logs(self, limit=50):
        rows = self._run(f"SELECT log_id, username, role, action, details, created_at FROM audit_logs ORDER BY log_id DESC LIMIT {int(limit)}")
        keys = ("log_id", "username", "role", "action", "details", "created_at")
        return [dict(zip(keys, r)) for r in rows]

    def seed_default_users(self):
        """Seed demo credentials for multiple roles: Staff, Patients, Donors, Admin."""
        # 1. Update demo persons with realistic friendly names and eligible donation status
        demo_names = {
            10: "Rahul Sharma (Patient)",
            1: "Priya Patel (Patient)",
            2: "Amit Singh (Patient)",
            3: "Vikram Malhotra (Donor)",
            4: "Sneha Rawat (Donor)",
            6: "Rohit Mehra (Donor)"
        }
        for pid, dname in demo_names.items():
            try:
                self._run(f"UPDATE persons SET name={self.ph} WHERE person_id={self.ph}", (dname, pid))
            except Exception:
                pass

        # Make donors eligible (available=1, last_donation > 90 days ago)
        for dpid in (3, 4, 6):
            try:
                self._run(f"UPDATE persons SET available=1, last_donation='2026-05-10' WHERE person_id={self.ph}", (dpid,))
            except Exception:
                pass

        # 2. Seed accounts
        # Admin & Staff
        if not self._run("SELECT 1 FROM users WHERE username='admin'"):
            self.register_user("admin", "admin123", role="ADMIN", created_at=0)
        if not self._run("SELECT 1 FROM users WHERE username='staff'"):
            self.register_user("staff", "staff123", role="STAFF", created_at=0)
        if not self._run("SELECT 1 FROM users WHERE username='staff_aiims'"):
            self.register_user("staff_aiims", "staff123", role="STAFF", created_at=0)

        def get_pid_if_exists(target_pid):
            p = self._run(f"SELECT person_id FROM persons WHERE person_id={self.ph}", (target_pid,))
            return p[0][0] if p else None

        # Baseline backward compatibility
        if not self._run("SELECT 1 FROM users WHERE username='user10'"):
            self.register_user("user10", "user123", role="USER", person_id=get_pid_if_exists(10), created_at=0)
        if not self._run("SELECT 1 FROM users WHERE username='user1'"):
            self.register_user("user1", "user123", role="USER", person_id=get_pid_if_exists(1), created_at=0)

        # Multiple Patients (Acceptors)
        if not self._run("SELECT 1 FROM users WHERE username='rahul'"):
            self.register_user("rahul", "user123", role="USER", person_id=get_pid_if_exists(10), created_at=0)
        if not self._run("SELECT 1 FROM users WHERE username='priya'"):
            self.register_user("priya", "user123", role="USER", person_id=get_pid_if_exists(1), created_at=0)
        if not self._run("SELECT 1 FROM users WHERE username='amit'"):
            self.register_user("amit", "user123", role="USER", person_id=get_pid_if_exists(2), created_at=0)

        # Multiple Voluntary Donors
        if not self._run("SELECT 1 FROM users WHERE username='vikram'"):
            self.register_user("vikram", "donor123", role="DONOR", person_id=get_pid_if_exists(3), created_at=0)
        if not self._run("SELECT 1 FROM users WHERE username='sneha'"):
            self.register_user("sneha", "donor123", role="DONOR", person_id=get_pid_if_exists(4), created_at=0)
        if not self._run("SELECT 1 FROM users WHERE username='rohit'"):
            self.register_user("rohit", "donor123", role="DONOR", person_id=get_pid_if_exists(6), created_at=0)

    def add_inventory_unit(self, hospital_id, blood_group, expiry_date):
        if blood_group not in rules.GROUPS:
            raise ValueError(f"Invalid blood group {blood_group}")
        ph = self.ph
        cur = self.conn.cursor()
        cur.execute(f"INSERT INTO inventory(hospital_id, blood_group, expiry_date, status) VALUES({ph},{ph},{ph},'AVAILABLE')",
                    (hospital_id, blood_group, str(expiry_date)))
        uid = cur.lastrowid
        cur.close()
        self.conn.commit()
        return uid

