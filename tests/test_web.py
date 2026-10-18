import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bloodapp import webapp
from bloodapp.bdb import BloodDB
from bloodapp.world import build_world
from sonetq.cache import SharedSnapshotStore
import blood_app

class TestWebApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        os.close(cls.db_fd)
        
        world = build_world(n_people=200, months=5, requests_per_month=5, new_social=50)
        blood_app.make_db(world, cls.db_path, with_future_requests=True)
        
        webapp.STATE["path"] = cls.db_path
        db = BloodDB("sqlite", cls.db_path)
        db.seed_default_users()
        webapp.STATE["latest"] = db._run("SELECT MAX(snapshot_id) FROM snapshots")[0][0]
        webapp.STATE["clock"] = db._run("SELECT COALESCE(MAX(created_at),0) FROM requests")[0][0]
        db.close()
        webapp.STATE["store"] = SharedSnapshotStore(lambda: BloodDB("sqlite", cls.db_path), capacity=5, policy="LRU")
        
        webapp.app.config["TESTING"] = True
        cls.client = webapp.app.test_client()

    @classmethod
    def tearDownClass(cls):
        try:
            for ext in ("", "-wal", "-shm"):
                p = cls.db_path + ext
                if os.path.exists(p): os.remove(p)
        except Exception:
            pass

    def test_homepage(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"SonetQ BloodConnect", res.data)

    def test_auth_flow(self):
        # 1. Unauthenticated /api/me
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 401)

        # 2. Wrong password
        r = self.client.post("/api/login", json={"username": "admin", "password": "wrong"})
        self.assertEqual(r.status_code, 401)

        # 3. Successful login as user10
        r = self.client.post("/api/login", json={"username": "user10", "password": "user123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["user"]["username"], "user10")
        self.assertEqual(r.get_json()["user"]["role"], "USER")

        # 4. Check me
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 200)

        # 5. Logout
        r = self.client.post("/api/logout")
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 401)

    def test_role_based_access_control(self):
        # Unauthenticated staff action -> 401
        r = self.client.post("/api/process", json={})
        self.assertEqual(r.status_code, 401)

        # Login as normal user (requester)
        self.client.post("/api/login", json={"username": "user10", "password": "user123"})
        # Attempt staff-only process -> 403 Forbidden!
        r = self.client.post("/api/process", json={})
        self.assertEqual(r.status_code, 403)
        # Attempt admin-only invariants -> 403 Forbidden!
        r = self.client.get("/api/invariants")
        self.assertEqual(r.status_code, 403)
        self.client.post("/api/logout")

        # Login as staff -> Allowed to process
        self.client.post("/api/login", json={"username": "staff", "password": "staff123"})
        r = self.client.post("/api/process", json={})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("status", data)
        self.assertIn("shortfall", data)
        self.client.post("/api/logout")

    def test_create_request_and_state(self):
        # Create request
        r = self.client.post("/api/request", json={
            "requester_id": 10,
            "blood_group": "O+",
            "city": "Dehradun",
            "units": 2,
            "priority": 0
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn("request_id", r.get_json())

        # Check state
        r = self.client.get("/api/state")
        self.assertEqual(r.status_code, 200)
        s = r.get_json()
        self.assertIn("inventory", s)
        self.assertIn("queue", s)
        self.assertIn("cache", s)
        self.assertGreater(len(s["queue"]), 0)

    def test_clock_advance_and_aging(self):
        self.client.post("/api/login", json={"username": "staff", "password": "staff123"})
        r = self.client.post("/api/clock/advance", json={"minutes": 15})
        self.assertEqual(r.status_code, 200)
        self.client.post("/api/logout")

    def test_admin_invariants(self):
        self.client.post("/api/login", json={"username": "admin", "password": "admin123"})
        r = self.client.get("/api/invariants")
        self.assertEqual(r.status_code, 200)
        inv = r.get_json()["invariants"]
        for k, v in inv.items():
            self.assertEqual(v, 0, f"Invariant failure: {k} = {v}")
        self.client.post("/api/logout")

    def test_multi_user_registration_and_profiles(self):
        # Register new patient
        r = self.client.post("/api/register", json={
            "name": "Kavya Rathi",
            "username": "kavya_test",
            "password": "pwd_test_123",
            "role": "USER",
            "blood_group": "O+",
            "city": "Dehradun",
            "age": 22
        })
        self.assertEqual(r.status_code, 200)
        u = r.get_json()["user"]
        self.assertEqual(u["username"], "kavya_test")
        self.assertEqual(u["role"], "USER")
        self.assertIsNotNone(u["person_id"])
        self.client.post("/api/logout")

        # Register new voluntary donor
        r = self.client.post("/api/register", json={
            "name": "Arjun Kapoor",
            "username": "arjun_test",
            "password": "pwd_test_123",
            "role": "DONOR",
            "blood_group": "B+",
            "city": "Haridwar",
            "age": 26
        })
        self.assertEqual(r.status_code, 200)
        u = r.get_json()["user"]
        self.assertEqual(u["role"], "DONOR")
        self.client.post("/api/logout")

    def test_donor_pledge_and_walkin(self):
        # Login as seeded donor Vikram
        r = self.client.post("/api/login", json={"username": "vikram", "password": "donor123"})
        self.assertEqual(r.status_code, 200)

        # Donor pledge for request #1
        r = self.client.post("/api/donor/pledge", json={"request_id": 1})
        self.assertEqual(r.status_code, 200)
        self.assertIn("recorded", r.get_json()["message"])

        # Donor walkin donation
        r = self.client.post("/api/donor/walkin_donate", json={"hospital_id": 1})
        self.assertEqual(r.status_code, 200)
        self.assertIn("unit_id", r.get_json())
        self.client.post("/api/logout")

    def test_audit_logs_access(self):
        # Non-admin cannot access audit logs
        self.client.post("/api/login", json={"username": "user10", "password": "user123"})
        r = self.client.get("/api/audit_logs")
        self.assertEqual(r.status_code, 403)
        self.client.post("/api/logout")

        # Admin can access audit logs
        self.client.post("/api/login", json={"username": "admin", "password": "admin123"})
        r = self.client.get("/api/audit_logs")
        self.assertEqual(r.status_code, 200)
        logs = r.get_json()["logs"]
        self.assertGreater(len(logs), 0)
        self.client.post("/api/logout")

    def test_graph_network_endpoint(self):
        r = self.client.get("/api/graph_network")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertIn("legend", data)
        # Check presence of blue patient dots and red donor dots
        has_patient = any(n.get("type") == "patient" for n in data["nodes"])
        has_donor = any(n.get("type") == "donor" for n in data["nodes"])
        self.assertTrue(has_patient, "Graph should contain patient nodes")
        self.assertTrue(has_donor, "Graph should contain donor nodes")


