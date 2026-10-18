"""DBMS layer (Phase 11).  MySQL is the 'source of truth'.
SQLite is a drop-in stand-in so the project also runs on a laptop without MySQL.

Tables:  snapshots(snapshot_id, start_ts, end_ts, num_edges)
         nodes(node_id, attributes)
         edges(edge_id, source, target, snapshot_id, ts)
         predictions(pred_id, source, target, target_snapshot, score, model)
"""
import sqlite3

INDEXES = {
    "idx_edges_snapshot": "edges(snapshot_id)",
    "idx_edges_source": "edges(source)",
    "idx_edges_target": "edges(target)",
    "idx_edges_ts": "edges(ts)",
}


class SnapshotDB:
    def __init__(self, backend="sqlite", sqlite_path=":memory:", mysql_cfg=None):
        self.backend = backend
        if backend == "mysql":
            try:
                import mysql.connector
            except ImportError as e:
                raise SystemExit("Run:  pip install mysql-connector-python") from e
            self.conn = mysql.connector.connect(**(mysql_cfg or {}))
            self.ph = "%s"
        else:
            self.conn = sqlite3.connect(sqlite_path, timeout=30)
            self.ph = "?"

    # ------------------------------------------------------------------ helpers
    def _run(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else []
        cur.close()
        return rows

    def _many(self, sql, rows):
        cur = self.conn.cursor()
        cur.executemany(sql, rows)
        cur.close()

    # ------------------------------------------------------------------- schema
    def create_schema(self):
        pk_auto = "INT AUTO_INCREMENT PRIMARY KEY" if self.backend == "mysql" \
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for t in ("predictions", "edges", "nodes", "snapshots"):
            self._run(f"DROP TABLE IF EXISTS {t}")
        self._run("""CREATE TABLE snapshots(
                        snapshot_id INT PRIMARY KEY, start_ts BIGINT, end_ts BIGINT, num_edges INT)""")
        self._run("CREATE TABLE nodes(node_id BIGINT PRIMARY KEY, attributes VARCHAR(255))")
        self._run(f"""CREATE TABLE edges(
                        edge_id {pk_auto}, source BIGINT NOT NULL, target BIGINT NOT NULL,
                        snapshot_id INT NOT NULL, ts BIGINT NOT NULL,
                        FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id))""")
        self._run(f"""CREATE TABLE predictions(
                        pred_id {pk_auto}, source BIGINT, target BIGINT,
                        target_snapshot INT, score DOUBLE, model VARCHAR(64))""")
        self.conn.commit()

    def create_indexes(self):
        for name, target in INDEXES.items():
            try:
                self._run(f"CREATE INDEX {name} ON {target}")
            except Exception:
                pass                       # already exists
        self.conn.commit()

    def drop_indexes(self):
        for name in INDEXES:
            try:
                if self.backend == "mysql":
                    self._run(f"DROP INDEX {name} ON edges")
                else:
                    self._run(f"DROP INDEX IF EXISTS {name}")
            except Exception:
                pass
        self.conn.commit()

    # ------------------------------------------------------------------ loading
    def load(self, snapshots, meta, names=None):
        """Bulk-load everything inside ONE transaction (all-or-nothing = Atomicity)."""
        try:
            nodes = sorted({x for edges in snapshots.values() for e in edges for x in e})
            ph = self.ph
            self._many(f"INSERT INTO snapshots VALUES({ph},{ph},{ph},{ph})",
                       [(i, meta[i][0], meta[i][1], len(snapshots[i])) for i in sorted(snapshots)])
            self._many(f"INSERT INTO nodes VALUES({ph},{ph})", [(n, (names or {}).get(n, "")[:250]) for n in nodes])
            rows = [(u, v, i, ts) for i in sorted(snapshots) for (u, v), ts in snapshots[i].items()]
            self._many(f"INSERT INTO edges(source,target,snapshot_id,ts) VALUES({ph},{ph},{ph},{ph})", rows)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------ queries
    def get_snapshot_edges(self, snapshot_id):
        return self._run(f"SELECT source, target FROM edges WHERE snapshot_id = {self.ph}", (snapshot_id,))

    def get_node_edges(self, node):
        return self._run(f"SELECT source, target, snapshot_id FROM edges "
                         f"WHERE source = {self.ph} OR target = {self.ph}", (node, node))

    def count_edges(self):
        return self._run("SELECT COUNT(*) FROM edges")[0][0]

    def save_predictions(self, model, target_snapshot, rows):
        ph = self.ph
        self._many(f"INSERT INTO predictions(source,target,target_snapshot,score,model) "
                   f"VALUES({ph},{ph},{ph},{ph},{ph})",
                   [(int(u), int(v), target_snapshot, float(s), model) for (u, v, s) in rows])
        self.conn.commit()

    def close(self):
        self.conn.close()
