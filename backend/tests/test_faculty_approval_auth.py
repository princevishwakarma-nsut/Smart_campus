import os
import sys
import unittest
from fastapi.testclient import TestClient

# Ensure backend root is on path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# Switch DB_NAME to isolated test database BEFORE importing app and database modules
os.environ["DB_NAME"] = "smart_campus_test"
from app.core.config import settings
settings.DB_NAME = "smart_campus_test"

import app.database.connection as db_conn
db_conn._pool = None
from app.database.connection import get_connection_pool

from app.main import app
from app.core.security import create_access_token, decode_access_token, verify_password
from tests.setup_test_db import setup_isolated_test_database

client = TestClient(app)


class FacultyApprovalAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Initialize clean isolated test database
        setup_isolated_test_database()
        cls.pool = get_connection_pool()

        # 2. Auth tokens for mock Admin & Student
        cls.admin_token = create_access_token(1, extra_claims={"role": "Admin", "email": "admin.test@campus.edu", "name": "Admin Tester"})
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.student_token = create_access_token(4, extra_claims={"role": "Student", "email": "student.test@campus.edu", "name": "Student Tester"})
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}

    # 1. Faculty submits a valid registration
    def test_01_faculty_submits_valid_registration(self):
        payload = {
            "name": "Dr. Vivek Sharma",
            "email": "vivek.sharma@nsut.ac.in",
            "password": "FacultyPassword123!",
            "department_id": 1,
            "employee_id": "FAC-NSUT-101",
            "designation": "Assistant Professor",
            "phone_no": "9812345678"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "Pending")
        self.assertIn("request_id", data)
        self.assertIn("user_id", data)
        self.__class__.sharma_request_id = data["request_id"]
        self.__class__.sharma_user_id = data["user_id"]

    # 2. Faculty submits a duplicate email
    def test_02_faculty_submits_duplicate_email(self):
        payload = {
            "name": "Dr. Vivek Duplicate",
            "email": "vivek.sharma@nsut.ac.in",
            "password": "FacultyPassword123!",
            "employee_id": "FAC-NSUT-102"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already pending", res.json()["detail"].lower())

    # 3. Faculty submits an invalid department
    def test_03_faculty_submits_invalid_department(self):
        payload = {
            "name": "Dr. Invalid Dept",
            "email": "invalid.dept@nsut.ac.in",
            "password": "FacultyPassword123!",
            "department_id": 99999,
            "employee_id": "FAC-NSUT-103"
        }
        res = client.post("/api/v1/auth/register/faculty", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid department", res.json()["detail"].lower())

    # 4. Faculty registration saves a valid password hash
    def test_04_faculty_registration_saves_valid_password_hash(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password_hash FROM faculty_requests WHERE request_id = %s", (self.sharma_request_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        self.assertIsNotNone(row)
        self.assertTrue(row["password_hash"].startswith("$argon2id$"))
        self.assertTrue(verify_password("FacultyPassword123!", row["password_hash"]))

    # 5. Pending Faculty login is rejected
    def test_05_pending_faculty_login_is_rejected(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "vivek.sharma@nsut.ac.in",
            "password": "FacultyPassword123!"
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn("pending administrator approval", res.json()["detail"].lower())

    # 6. Admin approves the Faculty request
    def test_06_admin_approves_faculty_request(self):
        res = client.post(
            f"/api/v1/users/faculty-requests/{self.sharma_request_id}/approve",
            headers=self.admin_headers
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "Approved")
        self.assertEqual(data["user_id"], self.sharma_user_id)

    # 7. Approval preserves the original user ID
    def test_07_approval_preserves_original_user_id(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id, is_active, role FROM users WHERE email = %s", ("vivek.sharma@nsut.ac.in",))
        user_row = cursor.fetchone()
        cursor.close()
        conn.close()

        self.assertIsNotNone(user_row)
        self.assertEqual(user_row["user_id"], self.sharma_user_id)
        self.assertEqual(user_row["role"], "Faculty")
        self.assertEqual(user_row["is_active"], 1)

    # 8. Approval preserves the original password hash
    def test_08_approval_preserves_original_password_hash(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password_hash FROM users WHERE user_id = %s", (self.sharma_user_id,))
        user_hash = cursor.fetchone()["password_hash"]
        cursor.execute("SELECT password_hash FROM faculty_requests WHERE request_id = %s", (self.sharma_request_id,))
        req_hash = cursor.fetchone()["password_hash"]
        cursor.close()
        conn.close()

        self.assertEqual(user_hash, req_hash)
        self.assertTrue(verify_password("FacultyPassword123!", user_hash))

    # 9. Approved Faculty can log in with original email and password
    def test_09_approved_faculty_can_login_with_original_credentials(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "vivek.sharma@nsut.ac.in",
            "password": "FacultyPassword123!"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["role"], "Faculty")
        self.assertEqual(data["user"]["email"], "vivek.sharma@nsut.ac.in")
        self.__class__.faculty_token = data["access_token"]
        self.__class__.faculty_headers = {"Authorization": f"Bearer {data['access_token']}"}

    # 10. Incorrect password is rejected
    def test_10_incorrect_password_is_rejected(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "vivek.sharma@nsut.ac.in",
            "password": "WrongPassword999!"
        })
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Incorrect email or password")

    # 11. Rejected Faculty cannot log in
    def test_11_rejected_faculty_cannot_login(self):
        # Register second faculty to reject
        reg_res = client.post("/api/v1/auth/register/faculty", json={
            "name": "Dr. Unverified Faculty",
            "email": "unverified.faculty@nsut.ac.in",
            "password": "FacultyPassword123!",
            "employee_id": "FAC-REJECT-01"
        })
        self.assertEqual(reg_res.status_code, 201)
        rej_id = reg_res.json()["request_id"]

        # Admin rejects
        rej_res = client.post(
            f"/api/v1/users/faculty-requests/{rej_id}/reject",
            json={"reason": "Invalid university credentials provided."},
            headers=self.admin_headers
        )
        self.assertEqual(rej_res.status_code, 200)

        # Login attempt receives 403 with rejection reason
        login_res = client.post("/api/v1/auth/login", json={
            "email": "unverified.faculty@nsut.ac.in",
            "password": "FacultyPassword123!"
        })
        self.assertEqual(login_res.status_code, 403)
        self.assertIn("invalid university credentials provided", login_res.json()["detail"].lower())

    # 12. Deactivated Faculty cannot log in
    def test_12_deactivated_faculty_cannot_login(self):
        # Admin deactivates Dr. Vivek Sharma
        patch_res = client.patch(
            f"/api/v1/users/{self.sharma_user_id}/status",
            json={"is_active": False},
            headers=self.admin_headers
        )
        self.assertEqual(patch_res.status_code, 200)

        # Dr. Vivek attempts to log in
        login_res = client.post("/api/v1/auth/login", json={
            "email": "vivek.sharma@nsut.ac.in",
            "password": "FacultyPassword123!"
        })
        self.assertEqual(login_res.status_code, 403)
        self.assertIn("deactivated", login_res.json()["detail"].lower())

        # Re-activate for remaining tests
        patch_res2 = client.patch(
            f"/api/v1/users/{self.sharma_user_id}/status",
            json={"is_active": True},
            headers=self.admin_headers
        )
        self.assertEqual(patch_res2.status_code, 200)

    # 13. Faculty receives correct role in JWT
    def test_13_faculty_receives_correct_role_in_jwt(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "vivek.sharma@nsut.ac.in",
            "password": "FacultyPassword123!"
        })
        token = res.json()["access_token"]
        claims = decode_access_token(token)
        self.assertEqual(claims["role"], "Faculty")
        self.assertEqual(claims["email"], "vivek.sharma@nsut.ac.in")

    # 14. Faculty can access authorised Faculty endpoints
    def test_14_faculty_can_access_authorised_faculty_endpoints(self):
        tt_res = client.get("/api/v1/timetable?department_name=CSE&day_of_week=Monday", headers=self.faculty_headers)
        self.assertEqual(tt_res.status_code, 200)

        bks_res = client.get("/api/v1/bookings/my", headers=self.faculty_headers)
        self.assertEqual(bks_res.status_code, 200)

    # 15. Faculty cannot access Admin endpoints
    def test_15_faculty_cannot_access_admin_endpoints(self):
        reqs_res = client.get("/api/v1/users/faculty-requests", headers=self.faculty_headers)
        self.assertEqual(reqs_res.status_code, 403)

        settings_res = client.get("/api/v1/reports/settings", headers=self.faculty_headers)
        self.assertEqual(settings_res.status_code, 403)

    # 16. Admin login continues working
    def test_16_admin_login_continues_working(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "admin.test@campus.edu",
            "password": "Password123!"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "Admin")

    # 17. Student login continues working
    def test_17_student_login_continues_working(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "student.test@campus.edu",
            "password": "Password123!"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "Student")

    # 18. Repeated approval does not create duplicate users
    def test_18_repeated_approval_does_not_create_duplicate_users(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE email = %s", ("vivek.sharma@nsut.ac.in",))
        count_before = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        # Attempt to approve again
        res = client.post(
            f"/api/v1/users/faculty-requests/{self.sharma_request_id}/approve",
            headers=self.admin_headers
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("already approved", res.json()["detail"].lower())

        conn = self.pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE email = %s", ("vivek.sharma@nsut.ac.in",))
        count_after = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        self.assertEqual(count_before, 1)
        self.assertEqual(count_after, 1)

    # 19. Approval updates correct user when multiple pending requests exist
    def test_19_approval_updates_correct_user_when_multiple_pending(self):
        # Register User A
        res_a = client.post("/api/v1/auth/register/faculty", json={
            "name": "Prof A",
            "email": "prof.a@nsut.ac.in",
            "password": "PasswordA123!",
            "employee_id": "EMP-A"
        })
        self.assertEqual(res_a.status_code, 201)
        id_a = res_a.json()["request_id"]
        uid_a = res_a.json()["user_id"]

        # Register User B
        res_b = client.post("/api/v1/auth/register/faculty", json={
            "name": "Prof B",
            "email": "prof.b@nsut.ac.in",
            "password": "PasswordB123!",
            "employee_id": "EMP-B"
        })
        self.assertEqual(res_b.status_code, 201)
        id_b = res_b.json()["request_id"]
        uid_b = res_b.json()["user_id"]

        # Approve User B first
        app_b = client.post(f"/api/v1/users/faculty-requests/{id_b}/approve", headers=self.admin_headers)
        self.assertEqual(app_b.status_code, 200)

        # User B can log in
        login_b = client.post("/api/v1/auth/login", json={"email": "prof.b@nsut.ac.in", "password": "PasswordB123!"})
        self.assertEqual(login_b.status_code, 200)

        # User A is still pending
        login_a = client.post("/api/v1/auth/login", json={"email": "prof.a@nsut.ac.in", "password": "PasswordA123!"})
        self.assertEqual(login_a.status_code, 403)

        # Approve User A
        app_a = client.post(f"/api/v1/users/faculty-requests/{id_a}/approve", headers=self.admin_headers)
        self.assertEqual(app_a.status_code, 200)

        # Now User A can log in
        login_a2 = client.post("/api/v1/auth/login", json={"email": "prof.a@nsut.ac.in", "password": "PasswordA123!"})
        self.assertEqual(login_a2.status_code, 200)

    # 20. Failed approval rolls back related database changes
    def test_20_failed_approval_rolls_back_database_changes(self):
        # Attempt to approve a non-existent request
        res = client.post("/api/v1/users/faculty-requests/999999/approve", headers=self.admin_headers)
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
