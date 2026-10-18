-- Blood application tables (MySQL 8).  Run after sql/schema_mysql.sql  (snapshots / nodes / edges already exist).
USE sonetq;
CREATE TABLE IF NOT EXISTS hospitals(hospital_id INT PRIMARY KEY, name VARCHAR(80) NOT NULL, city VARCHAR(40) NOT NULL);
CREATE TABLE IF NOT EXISTS persons(
  person_id BIGINT PRIMARY KEY, name VARCHAR(80) NOT NULL,
  blood_group VARCHAR(3) NOT NULL CHECK (blood_group IN ('A+','A-','B+','B-','AB+','AB-','O+','O-')),
  city VARCHAR(40) NOT NULL, birth_year INT NOT NULL, last_donation DATE NULL, available TINYINT NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS requests(
  request_id INT AUTO_INCREMENT PRIMARY KEY, requester_id BIGINT NOT NULL, hospital_id INT NOT NULL,
  blood_group VARCHAR(3) NOT NULL, city VARCHAR(40) NOT NULL,
  units_needed INT NOT NULL CHECK (units_needed > 0), units_allocated INT NOT NULL DEFAULT 0,
  priority INT NOT NULL CHECK (priority IN (0,1,2)),
  status VARCHAR(12) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','FULFILLED','PARTIAL','UNFULFILLED')),
  created_at INT NOT NULL,
  FOREIGN KEY (requester_id) REFERENCES persons(person_id), FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id));
CREATE TABLE IF NOT EXISTS inventory(
  unit_id INT AUTO_INCREMENT PRIMARY KEY, hospital_id INT NOT NULL, blood_group VARCHAR(3) NOT NULL,
  expiry_date DATE NOT NULL, status VARCHAR(10) NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE','ALLOCATED','EXPIRED')),
  request_id INT NULL, FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id), FOREIGN KEY (request_id) REFERENCES requests(request_id));
CREATE TABLE IF NOT EXISTS allocations(
  alloc_id INT AUTO_INCREMENT PRIMARY KEY, request_id INT NOT NULL, unit_id INT NOT NULL UNIQUE, allocated_on DATE NOT NULL,
  FOREIGN KEY (request_id) REFERENCES requests(request_id), FOREIGN KEY (unit_id) REFERENCES inventory(unit_id));
CREATE TABLE IF NOT EXISTS notifications(
  notif_id INT AUTO_INCREMENT PRIMARY KEY, request_id INT NOT NULL, donor_id BIGINT NOT NULL,
  rank_no INT NOT NULL, score DOUBLE NOT NULL, model VARCHAR(30) NOT NULL,
  FOREIGN KEY (request_id) REFERENCES requests(request_id), FOREIGN KEY (donor_id) REFERENCES persons(person_id));
CREATE INDEX idx_persons_group_city ON persons(blood_group, city);
CREATE INDEX idx_inventory_lookup  ON inventory(status, blood_group, expiry_date);
CREATE INDEX idx_requests_status   ON requests(status, priority);

-- the atomic allocation (what bdb.allocate_units does) in plain SQL:
-- START TRANSACTION;
--   SELECT blood_group, units_needed, units_allocated FROM requests WHERE request_id = ? FOR UPDATE;
--   SELECT unit_id FROM inventory WHERE status='AVAILABLE' AND expiry_date >= CURDATE() AND blood_group IN (...)
--     ORDER BY (blood_group = ?) DESC, expiry_date LIMIT ? FOR UPDATE;
--   UPDATE inventory SET status='ALLOCATED', request_id=? WHERE unit_id=? AND status='AVAILABLE';
--   INSERT INTO allocations(request_id, unit_id, allocated_on) VALUES(?,?,CURDATE());
--   UPDATE requests SET units_allocated = ?, status = ? WHERE request_id = ?;
-- COMMIT;   -- on any error: ROLLBACK;
