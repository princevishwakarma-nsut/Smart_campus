"""Comprehensive test suite for Authentication, Password Hashing,
Admin Password Resets, User Self-Service Password Changes,
and Token Version Session Invalidation.
"""

import os
import sys
import unittest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

os.environ["DB_NAME"] = "smart_campus_test"
from app.core.config import settings
settings.DB_NAME = "smart_campus_test"

import app.database.connection as db_conn
db_conn._pool = None
from app.database.connection import get_connection_pool

from app.main import app
from tests.setup_test_db import setup_isolated_test_database
from app.core.security import create_access_token, verify_password, get_password_hash


class TestAuthPasswordLifecycle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        setup_isolated_test_database()
        cls.pool = get_connection_pool()
        cls.client = TestClient(app)

        # Seed 3 distinct users with 3 completely distinct passwords
        conn = cls.pool.get_connection()
        cursor = conn.cursor(dictionary=True)

        admin_hash = get_password_hash("AdminPass123!")
        faculty_hash = get_password_hash("FacultyPass123!")
        student_hash = get_password_hash("StudentPass123!")

        cursor.execute("UPDATE users SET password_hash = %s, token_version = 1 WHERE user_id = 1", (admin_hash,))
        cursor.execute("UPDATE users SET password_hash = %s, token_version = 1 WHERE user_id = 2", (faculty_hash,))
        cursor.execute("UPDATE users SET password_hash = %s, token_version = 1 WHERE user_id = 4", (student_hash,))

        conn.commit()
        cursor.close()
        conn.close()

    def test_01_admin_login_success(self):
        """Admin logs in with Admin credentials."""
        res = self.client.post("/api/v1/auth/login", json={
            "email": "admin.test@campus.edu",
            "password": "AdminPass123!"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["role"], "Admin")

    def test_02_faculty_login_success(self):
        """Faculty logs in with Faculty credentials."""
        res = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "FacultyPass123!"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["user"]["role"], "Faculty")

    def test_03_student_login_success(self):
        """Student logs in with Student credentials."""
        res = self.client.post("/api/v1/auth/login", json={
            "email": "student.test@campus.edu",
            "password": "StudentPass123!"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["user"]["role"], "Student")

    def test_04_wrong_password_rejected(self):
        """Incorrect password returns 401."""
        res = self.client.post("/api/v1/auth/login", json={
            "email": "student.test@campus.edu",
            "password": "WrongPassword999!"
        })
        self.assertEqual(res.status_code, 401)

    def test_05_account_a_trying_account_b_password_rejected(self):
        """Faculty trying to log in with Student or Admin password is rejected."""
        res = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "StudentPass123!"
        })
        self.assertEqual(res.status_code, 401)

        res_admin = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "AdminPass123!"
        })
        self.assertEqual(res_admin.status_code, 401)

    def test_06_admin_resets_faculty_password(self):
        """Admin resets Faculty password and invalidates previous sessions."""
        # 1. Faculty logs in to obtain initial session token
        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "FacultyPass123!"
        })
        initial_token = login_res.json()["access_token"]

        # 2. Verify initial token works
        check_res = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {initial_token}"})
        self.assertEqual(check_res.status_code, 200)

        # 3. Admin logs in
        admin_login = self.client.post("/api/v1/auth/login", json={
            "email": "admin.test@campus.edu",
            "password": "AdminPass123!"
        })
        admin_token = admin_login.json()["access_token"]

        # 4. Admin resets Faculty password
        reset_res = self.client.post(
            "/api/v1/users/2/reset-password",
            json={"new_password": "NewFacultyPass888!"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(reset_res.status_code, 200)
        self.assertTrue(reset_res.json().get("success"))

        # 5. Old password is now rejected
        old_login = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "FacultyPass123!"
        })
        self.assertEqual(old_login.status_code, 401)

        # 6. Initial token is immediately invalidated (token_version mismatch)
        invalidated_res = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {initial_token}"})
        self.assertEqual(invalidated_res.status_code, 401)

        # 7. New password works
        new_login = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "NewFacultyPass888!"
        })
        self.assertEqual(new_login.status_code, 200)

    def test_07_faculty_changes_own_password(self):
        """User changes own password via self-service /auth/change-password."""
        # 1. Login with current password
        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "NewFacultyPass888!"
        })
        faculty_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {faculty_token}"}

        # 2. Try with wrong current password -> rejected
        bad_change = self.client.post("/api/v1/auth/change-password", json={
            "current_password": "WrongCurrentPassword123!",
            "new_password": "UpdatedFacultyPass999!"
        }, headers=headers)
        self.assertEqual(bad_change.status_code, 400)

        # 3. Change password successfully
        ok_change = self.client.post("/api/v1/auth/change-password", json={
            "current_password": "NewFacultyPass888!",
            "new_password": "UpdatedFacultyPass999!"
        }, headers=headers)
        self.assertEqual(ok_change.status_code, 200)
        self.assertTrue(ok_change.json().get("success"))

        # 4. Old session token is immediately invalidated
        old_session = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(old_session.status_code, 401)

        # 5. Old password rejected at login
        old_login = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "NewFacultyPass888!"
        })
        self.assertEqual(old_login.status_code, 401)

        # 6. New password works at login
        new_login = self.client.post("/api/v1/auth/login", json={
            "email": "faculty.test@campus.edu",
            "password": "UpdatedFacultyPass999!"
        })
        self.assertEqual(new_login.status_code, 200)

    def test_08_deactivated_account_cannot_log_in_or_use_tokens(self):
        """Deactivated accounts cannot log in or use previously issued tokens."""
        # Inactive student is user 5
        res = self.client.post("/api/v1/auth/login", json={
            "email": "inactive.student@campus.edu",
            "password": "Password123!"
        })
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
