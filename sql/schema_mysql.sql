-- Run once in MySQL Workbench / terminal:   mysql -u root -p < sql/schema_mysql.sql
CREATE DATABASE IF NOT EXISTS sonetq;
USE sonetq;
-- (run_all.py --backend mysql also creates these tables itself; this file is for your report/viva)

CREATE TABLE IF NOT EXISTS snapshots(
    snapshot_id INT PRIMARY KEY,
    start_ts BIGINT, end_ts BIGINT, num_edges INT);

CREATE TABLE IF NOT EXISTS nodes(
    node_id BIGINT PRIMARY KEY,
    attributes VARCHAR(255));

CREATE TABLE IF NOT EXISTS edges(
    edge_id INT AUTO_INCREMENT PRIMARY KEY,
    source BIGINT NOT NULL, target BIGINT NOT NULL,
    snapshot_id INT NOT NULL, ts BIGINT NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id));

CREATE TABLE IF NOT EXISTS predictions(
    pred_id INT AUTO_INCREMENT PRIMARY KEY,
    source BIGINT, target BIGINT, target_snapshot INT,
    score DOUBLE, model VARCHAR(64));

CREATE INDEX idx_edges_snapshot ON edges(snapshot_id);
CREATE INDEX idx_edges_source   ON edges(source);
CREATE INDEX idx_edges_target   ON edges(target);
CREATE INDEX idx_edges_ts       ON edges(ts);

-- Handy queries to show the panel after a run:
-- SELECT snapshot_id, num_edges FROM snapshots;
-- SELECT model, target_snapshot, COUNT(*) FROM predictions GROUP BY model, target_snapshot;
-- SELECT source, target, score FROM predictions WHERE model LIKE 'C:%' AND target_snapshot = 19 ORDER BY score DESC LIMIT 10;
