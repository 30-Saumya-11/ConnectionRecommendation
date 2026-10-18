import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bloodapp.bdb import BloodDB

class TestAuthAndAudit(unittest.TestCase):
    def setUp(self):
        self.db = BloodDB("sqlite", ":memory:")
        self.db.create_blood_schema()

    def tearDown(self):
        self.db.close()

    def test_registration_and_verification(self):
        uid = self.db.register_user("dr_sharma", "SecurePass123", role="STAFF")
        self.assertGreater(uid, 0)
        
        # Correct password
        user = self.db.verify_user("dr_sharma", "SecurePass123")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "dr_sharma")
        self.assertEqual(user["role"], "STAFF")

        # Wrong password
        self.assertIsNone(self.db.verify_user("dr_sharma", "WrongPass"))
        # Nonexistent user
        self.assertIsNone(self.db.verify_user("nonexistent", "Pass"))

    def test_duplicate_username_fails(self):
        self.db.register_user("admin_user", "pass1", role="ADMIN")
        with self.assertRaises(Exception):
            self.db.register_user("admin_user", "pass2", role="ADMIN")

    def test_audit_logging(self):
        self.db.log_audit("staff_1", "STAFF", "ALLOCATE_REQUEST", "Request #42 fulfilled 2 units", created_at=10)
        logs = self.db.get_audit_logs(limit=10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["username"], "staff_1")
        self.assertEqual(logs[0]["action"], "ALLOCATE_REQUEST")

    def test_seed_default_users(self):
        self.db.seed_default_users()
        admin = self.db.verify_user("admin", "admin123")
        self.assertIsNotNone(admin)
        self.assertEqual(admin["role"], "ADMIN")

        staff = self.db.verify_user("staff", "staff123")
        self.assertIsNotNone(staff)
        self.assertEqual(staff["role"], "STAFF")
