import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

# Ensure backend root is on path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# Switch DB_NAME to isolated test database BEFORE importing app and database modules
os.environ["DB_NAME"] = "smart_campus_test"
from app.core.config import settings
settings.DB_NAME = "smart_campus_test"

# Re-initialize pool against smart_campus_test
import app.database.connection as db_conn
db_conn._pool = None
from app.database.connection import get_connection_pool

from app.main import app
from app.core.security import create_access_token
from tests.setup_test_db import setup_isolated_test_database

client = TestClient(app)


class RegistrationWorkflowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Initialize clean isolated test database
        setup_isolated_test_database()
        cls.pool = get_connection_pool()

        # 2. Auth tokens for mock users
        cls.admin_token = create_access_token(1, extra_claims={"role": "Admin", "email": "admin.test@campus.edu", "name": "Admin Tester"})
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.student_token = create_access_token(4, extra_claims={"role": "Student", "email": "student.test@campus.edu", "name": "Student Tester"})
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}

    # ==========================================
    # 1. STUDENT REGISTRATION TESTS
    # ==========================================
    def test_01_valid_student_registration(self):
        """Student registers successfully; backend forces role=Student."""
        payload = {
            "name": "Alice Student",
            "email": "alice.student@campus.edu",
            "password": "Password123!",
            "department_id": 1,
            "phone_no": "+91 9876543210",
            "role": "Admin"  # Attempt to escalate role - backend must ignore/reject
        }
        # In our auth.py, passing non-student role is rejected with 403, or when omitted/student defaults to Student
        res_escalate = client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res_escalate.status_code, 403)

        # Valid payload
        payload["role"] = "Student"
        res = client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["role"], "Student")
        self.assertEqual(data["email"], "alice.student@campus.edu")
        self.assertTrue(data["is_active"])

        # Verify auto-login works immediately
        login_res = client.post("/api/v1/auth/login", json={"email": "alice.student@campus.edu", "password": "Password123!"})
        self.assertEqual(login_res.status_code, 200)
        self.assertIn("access_token", login_res.json())

    def test_02_student_duplicate_email_rejected(self):
        """Student registration with existing email returns 400 Bad Request."""
        payload = {
            "name": "Alice Duplicate",
            "email": "alice.student@campus.edu",
            "password": "Password123!",
            "role": "Student"
        }
        res = client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", res.json()["detail"].lower())

    def test_03_student_invalid_department_rejected(self):
        """Student registration with non-existent department_id returns 400."""
        payload = {
            "name": "Bob Invalid Dept",
            "email": "bob.invaliddept@campus.edu",
            "password": "Password123!",
            "department_id": 99999,
            "role": "Student"
        }
        res = client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid department", res.json()["detail"].lower())

    def test_04_student_weak_password_rejected(self):
        """Student registration with password < 8 chars returns 422 Unprocessable Entity."""
        payload = {
            "name": "Charlie Weak",
            "email": "charlie.weak@campus.edu",
            "password": "short",
            "role": "Student"
        }
        res = client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res.status_code, 422)

    # ==========================================
    # 2. FACULTY REGISTRATION REQUEST TESTS
    # ==========================================
    def test_05_valid_faculty_registration_request(self):
        """Faculty submits request; status is Pending; account not immediately active."""
        payload = {
            "name": "Dr. Robert Smith",
            "email": "robert.smith@campus.edu",
            "password": "FacultySecurePass123!",
            "department_id": 1,
            "employee_id": "FAC-2026-091",
            "designation": "Associate Professor",
            "phone_no": "+91 9988776655"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "Pending")
        self.assertIn("request_id", data)
        self.__class__.faculty_request_id = data["request_id"]

    def test_06_unapproved_faculty_cannot_login(self):
        """Unapproved faculty attempting to log in receives 403 Forbidden."""
        res = client.post("/api/v1/auth/login", json={
            "email": "robert.smith@campus.edu",
            "password": "FacultySecurePass123!"
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn("pending administrator approval", res.json()["detail"].lower())

    def test_07_faculty_duplicate_email_rejected(self):
        """Submitting duplicate faculty request with same pending email returns 400."""
        payload = {
            "name": "Dr. Robert Smith Clone",
            "email": "robert.smith@campus.edu",
            "password": "FacultySecurePass123!",
            "employee_id": "FAC-2026-099"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already pending", res.json()["detail"].lower())

    def test_08_faculty_existing_user_email_rejected(self):
        """Submitting faculty request with email already in users table returns 400."""
        payload = {
            "name": "Duplicate User",
            "email": "alice.student@campus.edu",  # already registered student
            "password": "FacultySecurePass123!",
            "employee_id": "FAC-2026-101"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", res.json()["detail"].lower())

    def test_09_faculty_invalid_department_rejected(self):
        """Faculty request with invalid department_id returns 400."""
        payload = {
            "name": "Dr. Invalid Dept",
            "email": "invalid.dept.faculty@campus.edu",
            "password": "FacultySecurePass123!",
            "department_id": 99999,
            "employee_id": "FAC-2026-102"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid department", res.json()["detail"].lower())

    def test_10_faculty_missing_required_employee_id(self):
        """Faculty request missing employee_id returns 422 Unprocessable Entity."""
        payload = {
            "name": "Dr. No Emp ID",
            "email": "no.empid@campus.edu",
            "password": "FacultySecurePass123!"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 422)

    def test_11_faculty_weak_password_rejected(self):
        """Faculty request with password < 8 chars returns 422."""
        payload = {
            "name": "Dr. Short Pass",
            "email": "short.pass@campus.edu",
            "password": "short",
            "employee_id": "FAC-2026-103"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 422)

    def test_12_student_cannot_access_admin_faculty_requests(self):
        """Student attempting to list faculty requests receives 403 Forbidden."""
        res = client.get("/api/v1/users/faculty-requests", headers=self.student_headers)
        self.assertEqual(res.status_code, 403)

    def test_13_admin_lists_and_approves_faculty_request(self):
        """Admin views pending faculty request and approves it; user created as Faculty."""
        # Admin lists requests
        list_res = client.get("/api/v1/users/faculty-requests", headers=self.admin_headers)
        self.assertEqual(list_res.status_code, 200)
        reqs = list_res.json()
        target = next((r for r in reqs if r["email"] == "robert.smith@campus.edu"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["status"], "Pending")

        # Admin approves request
        app_res = client.post(f"/api/v1/users/faculty-requests/{target['request_id']}/approve", headers=self.admin_headers)
        self.assertEqual(app_res.status_code, 200)
        self.assertEqual(app_res.json()["status"], "Approved")

        # Verify newly approved faculty can now log in successfully
        login_res = client.post("/api/v1/auth/login", json={
            "email": "robert.smith@campus.edu",
            "password": "FacultySecurePass123!"
        })
        self.assertEqual(login_res.status_code, 200)
        login_data = login_res.json()
        self.assertEqual(login_data["user"]["role"], "Faculty")
        self.assertEqual(login_data["user"]["name"], "Dr. Robert Smith")

    def test_14_admin_rejects_faculty_request(self):
        """Admin rejects faculty request; status is Rejected; login shows rejection reason."""
        # 1. Submit another faculty request
        payload = {
            "name": "Unverified Faculty",
            "email": "unverified@campus.edu",
            "password": "Password123!",
            "employee_id": "FAC-UNKNOWN"
        }
        sub_res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(sub_res.status_code, 201)
        req_id = sub_res.json()["request_id"]

        # 2. Admin rejects request
        rej_res = client.post(
            f"/api/v1/users/faculty-requests/{req_id}/reject",
            json={"reason": "Staff ID FAC-UNKNOWN not found in university HR records."},
            headers=self.admin_headers
        )
        self.assertEqual(rej_res.status_code, 200)
        self.assertEqual(rej_res.json()["status"], "Rejected")

        # 3. Rejected faculty attempts login -> 403 Forbidden with specific reason
        login_res = client.post("/api/v1/auth/login", json={
            "email": "unverified@campus.edu",
            "password": "Password123!"
        })
        self.assertEqual(login_res.status_code, 403)
        self.assertIn("not found in university hr records", login_res.json()["detail"].lower())

    # ==========================================
    # 3. SOCIETY REGISTRATION TESTS
    # ==========================================
    def test_15_society_nonexistent_coordinator_rejected(self):
        """Society registration without a registered coordinator account returns 400."""
        payload = {
            "club_name": "Ghost Club",
            "coordinator_email": "nonexistent.user@campus.edu"
        }
        res = client.post("/api/v1/auth/register/society", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("was not found", res.json()["detail"].lower())

    def test_16_valid_society_registration(self):
        """Society registered with valid student coordinator; starts in Pending/inactive state."""
        payload = {
            "club_name": "Campus AI Society",
            "department_id": 1,
            "description": "Student machine learning and AI research club",
            "established_year": 2026,
            "coordinator_email": "alice.student@campus.edu"  # Registered in test 01
        }
        res = client.post("/api/v1/auth/register/society", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "Pending")
        self.assertIn("club_id", data)
        self.__class__.society_club_id = data["club_id"]

    def test_17_society_duplicate_name_rejected(self):
        """Society registration with duplicate name returns 400 Bad Request."""
        payload = {
            "club_name": "Campus AI Society",
            "coordinator_email": "alice.student@campus.edu"
        }
        res = client.post("/api/v1/auth/register/society", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", res.json()["detail"].lower())

    def test_18_society_invalid_department_rejected(self):
        """Society registration with invalid department returns 400."""
        payload = {
            "club_name": "Astronomical Society",
            "department_id": 99999,
            "coordinator_email": "alice.student@campus.edu"
        }
        res = client.post("/api/v1/auth/register/society", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid department", res.json()["detail"].lower())

    def test_19_pending_society_hidden_from_public_catalog(self):
        """Non-admin user cannot see Pending society in public societies list."""
        res = client.get("/api/v1/societies", headers=self.student_headers)
        self.assertEqual(res.status_code, 200)
        names = [s["club_name"] for s in res.json()]
        self.assertNotIn("Campus AI Society", names)

    def test_20_pending_society_booking_rejected(self):
        """Attempting to book space on behalf of an unapproved society returns 400."""
        # Alice logs in to get student token
        login_res = client.post("/api/v1/auth/login", json={"email": "alice.student@campus.edu", "password": "Password123!"})
        alice_token = login_res.json()["access_token"]
        alice_headers = {"Authorization": f"Bearer {alice_token}"}

        now = datetime.now(timezone.utc)
        start_dt = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        end_dt = (now + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)

        payload = {
            "society_id": self.society_club_id,
            "purpose": "AI Workshop",
            "attendees_count": 25,
            "resources": [{
                "resource_id": 1,
                "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end_dt.strftime("%Y-%m-%d %H:%M:%S")
            }]
        }
        res = client.post("/api/v1/bookings", json=payload, headers=alice_headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("not active or has not been approved", res.json()["detail"].lower())

    def test_21_student_cannot_approve_society(self):
        """Student attempting to approve a society receives 403 Forbidden."""
        res = client.post(f"/api/v1/societies/{self.society_club_id}/approve", headers=self.student_headers)
        self.assertEqual(res.status_code, 403)

    def test_22_admin_approves_society(self):
        """Admin approves society; becomes active and appears in catalog."""
        res = client.post(f"/api/v1/societies/{self.society_club_id}/approve", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "Approved")
        self.assertTrue(data["is_active"])

        # Now non-admin can see it in public catalog
        cat_res = client.get("/api/v1/societies", headers=self.student_headers)
        names = [s["club_name"] for s in cat_res.json()]
        self.assertIn("Campus AI Society", names)

    def test_23_approved_society_coordinator_can_book(self):
        """Coordinator can now successfully book space on behalf of approved society."""
        login_res = client.post("/api/v1/auth/login", json={"email": "alice.student@campus.edu", "password": "Password123!"})
        alice_token = login_res.json()["access_token"]
        alice_headers = {"Authorization": f"Bearer {alice_token}"}

        now = datetime.now(timezone.utc)
        start_dt = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        end_dt = (now + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)

        payload = {
            "society_id": self.society_club_id,
            "purpose": "AI Inaugural Workshop",
            "attendees_count": 25,
            "resources": [{
                "resource_id": 1,
                "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end_dt.strftime("%Y-%m-%d %H:%M:%S")
            }]
        }
        res = client.post("/api/v1/bookings", json=payload, headers=alice_headers)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["society_id"], self.society_club_id)

    def test_24_admin_rejects_society(self):
        """Admin rejects another society registration; status updated to Rejected."""
        # 1. Register a society to reject
        sub_res = client.post("/api/v1/auth/register/society", json={
            "club_name": "Unsanctioned Club",
            "coordinator_email": "alice.student@campus.edu"
        })
        self.assertEqual(sub_res.status_code, 201)
        club_id = sub_res.json()["club_id"]

        # 2. Admin rejects
        rej_res = client.post(
            f"/api/v1/societies/{club_id}/reject",
            json={"reason": "Faculty sponsor and constitution documentation missing."},
            headers=self.admin_headers
        )
        self.assertEqual(rej_res.status_code, 200)
        self.assertEqual(rej_res.json()["status"], "Rejected")
        self.assertFalse(rej_res.json()["is_active"])


if __name__ == "__main__":
    unittest.main()
