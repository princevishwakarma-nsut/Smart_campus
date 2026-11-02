"""Integration tests for Faculty Timetable Assignments, Isolated Professor Schedules,
and Sports Complex / Sports Facility resources.
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
from app.core.security import create_access_token


class TestTimetableEquipmentFlow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        setup_isolated_test_database()
        cls.pool = get_connection_pool()
        cls.client = TestClient(app)

        conn = cls.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        # Create Professor B (user_id: 10, Faculty)
        cursor.execute("""
            INSERT IGNORE INTO users (user_id, department_id, name, email, password_hash, role, is_active)
            VALUES (10, 1, 'Prof B Tester', 'prof.b@campus.edu', 'hash', 'Faculty', 1)
        """)
        conn.commit()
        cursor.close()
        conn.close()

        cls.admin_token = create_access_token(1, extra_claims={"email": "admin.test@campus.edu", "role": "Admin", "name": "Admin Tester"})
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        # Professor A (user_id: 2, Faculty)
        cls.prof_a_token = create_access_token(2, extra_claims={"email": "faculty.test@campus.edu", "role": "Faculty", "name": "Faculty Tester"})
        cls.prof_a_headers = {"Authorization": f"Bearer {cls.prof_a_token}"}

        # Professor B (user_id: 10, Faculty)
        cls.prof_b_token = create_access_token(10, extra_claims={"email": "prof.b@campus.edu", "role": "Faculty", "name": "Prof B Tester"})
        cls.prof_b_headers = {"Authorization": f"Bearer {cls.prof_b_token}"}

        # Student (user_id: 4, Student)
        cls.student_token = create_access_token(4, extra_claims={"email": "student.test@campus.edu", "role": "Student", "name": "Student Tester"})
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}

    def test_01_sports_facilities_seeded(self):
        """Verify Sports Facility category and 6 facilities exist and are bookable."""
        res = self.client.get("/api/v1/resources?category_id=6")
        self.assertEqual(res.status_code, 200)
        items = res.json()
        codes = [it["resource_code"] for it in items]
        self.assertIn("SPT-CMPLX", codes)
        self.assertIn("SPT-FTB-GRD", codes)
        self.assertIn("SPT-BSK-CRT", codes)
        self.assertIn("SPT-VLB-CRT", codes)
        self.assertIn("SPT-BAD-CRT", codes)
        self.assertIn("SPT-TNS-CRT", codes)

    def test_02_professor_starts_with_empty_schedule(self):
        """Unassigned faculty members see empty schedule, not full dept timetable."""
        res = self.client.get("/api/v1/timetable/my", headers=self.prof_a_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data, [])

    def test_03_admin_assigns_faculty_to_slot(self):
        """Admin assigns Professor A to timetable entry."""
        res_list = self.client.get("/api/v1/timetable/assignments", headers=self.admin_headers)
        self.assertEqual(res_list.status_code, 200)
        items = res_list.json()
        self.assertTrue(len(items) > 0)
        target_id = items[0]["timetable_id"]
        self.__class__.assigned_target_id = target_id

        res = self.client.post(
            f"/api/v1/timetable/{target_id}/assign",
            json={"faculty_user_ids": [2]},
            headers=self.admin_headers
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("success"))

        # Professor A now sees timetable slot
        res = self.client.get("/api/v1/timetable/my", headers=self.prof_a_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["timetable_id"], target_id)

        # Professor B still sees an empty schedule (strict isolation between faculty)
        res_b = self.client.get("/api/v1/timetable/my", headers=self.prof_b_headers)
        self.assertEqual(res_b.status_code, 200)
        self.assertEqual(res_b.json(), [])

    def test_04_admin_assignment_listing_and_filters(self):
        """Admin can list assignments, filter by department, and see assigned faculty."""
        target_id = getattr(self.__class__, "assigned_target_id", 1)
        res = self.client.get("/api/v1/timetable/assignments?department_name=CSE", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertTrue(len(items) > 0)
        assigned_slot = next((it for it in items if it["timetable_id"] == target_id), None)
        self.assertIsNotNone(assigned_slot)
        assigned_user_ids = [f["user_id"] for f in assigned_slot["assigned_faculty"]]
        self.assertIn(2, assigned_user_ids)

    def test_05_admin_unassigns_faculty(self):
        """Admin removes Professor A from timetable entry."""
        target_id = getattr(self.__class__, "assigned_target_id", 1)
        res = self.client.delete(f"/api/v1/timetable/{target_id}/assignments/2", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)

        # Professor A's schedule is empty again
        res = self.client.get("/api/v1/timetable/my", headers=self.prof_a_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

    def test_06_student_cannot_access_faculty_or_admin_timetable_endpoints(self):
        """Verify role-based authorization: Students cannot access timetable assignment management."""
        res = self.client.get("/api/v1/timetable/my", headers=self.student_headers)
        self.assertEqual(res.status_code, 403)

        res = self.client.get("/api/v1/timetable/assignments", headers=self.student_headers)
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
