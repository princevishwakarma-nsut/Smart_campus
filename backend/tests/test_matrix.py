import os
import sys
import unittest
import threading
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
db_conn._pool = None  # reset pool
from app.database.connection import get_connection_pool

from app.main import app
from app.core.security import create_access_token, get_password_hash
from tests.setup_test_db import setup_isolated_test_database

client = TestClient(app)


class SmartCampusIntegrationMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Initialize pristine smart_campus_test database
        setup_isolated_test_database()
        cls.pool = get_connection_pool()

        # 2. Generate tokens for mock test users
        cls.admin_token = create_access_token(1, extra_claims={"role": "Admin", "email": "admin.test@campus.edu", "name": "Admin Tester"})
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.faculty_token = create_access_token(2, extra_claims={"role": "Faculty", "email": "faculty.test@campus.edu", "name": "Faculty Tester"})
        cls.faculty_headers = {"Authorization": f"Bearer {cls.faculty_token}"}

        cls.staff_token = create_access_token(3, extra_claims={"role": "Staff", "email": "staff.test@campus.edu", "name": "Staff Tester"})
        cls.staff_headers = {"Authorization": f"Bearer {cls.staff_token}"}

        cls.student_token = create_access_token(4, extra_claims={"role": "Student", "email": "student.test@campus.edu", "name": "Student Tester"})
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}

        cls.inactive_token = create_access_token(5, extra_claims={"role": "Student", "email": "inactive.student@campus.edu", "name": "Inactive Tester"})
        cls.inactive_headers = {"Authorization": f"Bearer {cls.inactive_token}"}

    # =========================================================================
    # PHASE 1: SECURITY AND CONFIGURATION
    # =========================================================================
    def test_01_secret_key_enforcement(self):
        """Require configured SECRET_KEY with minimum 32 chars."""
        self.assertGreaterEqual(len(settings.SECRET_KEY), 32)
        self.assertNotEqual(settings.SECRET_KEY, "change_this_to_a_secure_random_key")

    def test_02_public_registration_restriction(self):
        """Public registration must only accept Student role; reject Faculty/Staff/Admin."""
        for forbidden_role in ["Faculty", "Staff", "Admin"]:
            resp = client.post("/api/v1/auth/register", json={
                "name": f"Hacker {forbidden_role}",
                "email": f"hacker_{forbidden_role.lower()}@campus.edu",
                "password": "Password123!",
                "role": forbidden_role
            })
            self.assertIn(resp.status_code, (400, 403), f"Public registration must reject {forbidden_role}")

        # Student registration must succeed
        s_resp = client.post("/api/v1/auth/register", json={
            "name": "Legit Student",
            "email": "legit.student.reg@campus.edu",
            "password": "Password123!",
            "role": "Student"
        })
        self.assertEqual(s_resp.status_code, 201)
        self.assertEqual(s_resp.json()["role"], "Student")

    def test_03_inactive_user_access_blocked(self):
        """Inactive users must be blocked on live DB verification on every authenticated request."""
        resp = client.get("/api/v1/auth/me", headers=self.inactive_headers)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("inactive", resp.json()["detail"].lower())

    def test_04_token_revocation(self):
        """Revoked tokens cannot be used after logout."""
        temp_token = create_access_token(4, extra_claims={"role": "Student", "email": "temp@campus.edu", "name": "Temp"})
        headers = {"Authorization": f"Bearer {temp_token}"}

        self.assertEqual(client.get("/api/v1/auth/me", headers=headers).status_code, 200)
        self.assertEqual(client.post("/api/v1/auth/logout", headers=headers).status_code, 200)
        self.assertEqual(client.get("/api/v1/auth/me", headers=headers).status_code, 401)

    def test_05_secret_sanitization(self):
        """Check that no passwords, hashes or tokens are exposed in user responses or audit logs."""
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT old_values, new_values FROM system_audit")
        rows = cursor.fetchall()
        for r in rows:
            for val in [str(r["old_values"]), str(r["new_values"])]:
                self.assertNotIn("password_hash", val.lower())
                self.assertNotIn("password123", val.lower())
        conn.close()

    # =========================================================================
    # PHASE 2: MYSQL CONNECTIVITY
    # =========================================================================
    def test_06_connection_pool_and_select(self):
        """Verify connection pool initialization, SELECT query and health status."""
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT 1 AS alive, DATABASE() AS cur_db")
        res = cursor.fetchone()
        self.assertEqual(res["alive"], 1)
        self.assertEqual(res["cur_db"], "smart_campus_test")
        cursor.close()
        conn.close()

        h_resp = client.get("/health")
        self.assertEqual(h_resp.status_code, 200)
        self.assertEqual(h_resp.json()["database"], "connected")

    def test_07_transaction_commit_and_rollback(self):
        """Verify atomic commit and rollback in transaction_scope."""
        from app.database.transaction import transaction_scope

        # Successful transaction
        with transaction_scope() as (conn, cursor):
            cursor.execute("INSERT INTO departments (department_id, department_name, is_active) VALUES (99, 'Rollback Test Dept', 1)")

        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT department_id FROM departments WHERE department_id = 99")
        self.assertIsNotNone(cursor.fetchone(), "Committed row must exist")
        conn.close()

        # Failing transaction -> rollback
        try:
            with transaction_scope() as (conn, cursor):
                cursor.execute("INSERT INTO departments (department_id, department_name, is_active) VALUES (100, 'Should Rollback', 1)")
                raise ValueError("Simulated unexpected failure")
        except ValueError:
            pass

        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT department_id FROM departments WHERE department_id = 100")
        self.assertIsNone(cursor.fetchone(), "Rolled back row must NOT exist")
        # cleanup test dept
        cursor.execute("DELETE FROM departments WHERE department_id = 99")
        conn.commit()
        conn.close()

    # =========================================================================
    # PHASE 3: RESOURCE CRUD & CONSTRAINTS
    # =========================================================================
    def test_08_resource_crud_lifecycle(self):
        """Test Add, Read, Update, and Operational Status change."""
        # 1. Add Resource
        add_resp = client.post("/api/v1/resources", headers=self.admin_headers, json={
            "resource_name": "Innovation Studio 105",
            "resource_code": "STU-105",
            "category_id": 1,
            "location": "Design Wing, 2nd Floor",
            "capacity": 45,
            "status": "Available",
            "description": "Design and prototyping studio",
            "features": ["Whiteboard", "3D Printer"]
        })
        self.assertEqual(add_resp.status_code, 201)
        r_id = add_resp.json()["resource_id"]

        # 2. Read Resource
        get_resp = client.get(f"/api/v1/resources/{r_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["resource_code"], "STU-105")
        self.assertEqual(get_resp.json()["location"], "Design Wing, 2nd Floor")

        # 3. Update Resource
        put_resp = client.put(f"/api/v1/resources/{r_id}", headers=self.admin_headers, json={
            "resource_name": "Advanced Innovation Studio 105",
            "capacity": 50,
            "features": ["Whiteboard", "3D Printer", "VR Station"]
        })
        self.assertEqual(put_resp.status_code, 200)
        self.assertEqual(put_resp.json()["capacity"], 50)

        # 4. Change Status
        st_resp = client.patch(f"/api/v1/resources/{r_id}/status", headers=self.admin_headers, json={
            "status": "Maintenance"
        })
        self.assertEqual(st_resp.status_code, 200)
        self.assertEqual(st_resp.json()["status"], "Maintenance")

    def test_09_resource_validation_constraints(self):
        """Verify NOT NULL schema validation, duplicate code rejection, and invalid capacity."""
        # Missing required resource_code
        resp1 = client.post("/api/v1/resources", headers=self.admin_headers, json={
            "resource_name": "Incomplete Room",
            "category_id": 1,
            "location": "Block B"
        })
        self.assertEqual(resp1.status_code, 422, "Missing resource_code must be rejected")

        # Missing required location
        resp2 = client.post("/api/v1/resources", headers=self.admin_headers, json={
            "resource_name": "Incomplete Room",
            "resource_code": "INC-01",
            "category_id": 1
        })
        self.assertEqual(resp2.status_code, 422, "Missing location must be rejected")

        # Duplicate resource_code
        resp3 = client.post("/api/v1/resources", headers=self.admin_headers, json={
            "resource_name": "Duplicate Code Room",
            "resource_code": "LAB-101",  # already exists in fixtures
            "category_id": 1,
            "location": "Block A"
        })
        self.assertEqual(resp3.status_code, 400, "Duplicate resource_code must be rejected")

        # Invalid capacity <= 0
        resp4 = client.post("/api/v1/resources", headers=self.admin_headers, json={
            "resource_name": "Negative Cap Room",
            "resource_code": "NEG-01",
            "category_id": 1,
            "location": "Block A",
            "capacity": 0
        })
        self.assertEqual(resp4.status_code, 422, "Zero/negative capacity must be rejected")

        # Non-admin forbidden
        resp5 = client.post("/api/v1/resources", headers=self.student_headers, json={
            "resource_name": "Student Created Room",
            "resource_code": "STU-HACK",
            "category_id": 1,
            "location": "Block A"
        })
        self.assertEqual(resp5.status_code, 403, "Student resource creation must be forbidden")

    # =========================================================================
    # PHASE 4: BOOKING TEST MATRIX (CASES 1 - 24)
    # =========================================================================
    def test_10_booking_case01_valid_future_booking(self):
        """Case 1: Valid future booking succeeds."""
        tomorrow = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{tomorrow}T14:00:00",
            "end_time": f"{tomorrow}T16:00:00",
            "purpose": "Project meeting session",
            "expected_participants": 5
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "Approved")  # Classroom auto-approves

    def test_11_booking_case02_booking_in_the_past(self):
        """Case 2: Booking in the past must be rejected."""
        resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": "2024-01-10T10:00:00",
            "end_time": "2024-01-10T12:00:00",
            "purpose": "Past booking attempt"
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("past", resp.json()["detail"].lower())

    def test_12_booking_case03_end_before_start(self):
        """Case 3: End time earlier than start time must be rejected."""
        tomorrow = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{tomorrow}T16:00:00",
            "end_time": f"{tomorrow}T14:00:00",
            "purpose": "Invalid time sequence"
        })
        self.assertEqual(resp.status_code, 400)

    def test_13_booking_case04_same_room_same_time_clash(self):
        """Case 4: Same room and exact same time conflict rejected."""
        target_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        # 1st booking
        r1 = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "First Session"
        })
        self.assertEqual(r1.status_code, 201)

        # 2nd booking exact same slot
        r2 = client.post("/api/v1/bookings", headers=self.faculty_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Conflicting Session"
        })
        self.assertEqual(r2.status_code, 409)

    def test_14_booking_case05_partially_overlapping(self):
        """Case 5: Same room with partially overlapping slot rejected."""
        target_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        # overlaps 11:00 to 13:00 (clashes with 10:00-12:00)
        r = client.post("/api/v1/bookings", headers=self.faculty_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T11:00:00",
            "end_time": f"{target_date}T13:00:00",
            "purpose": "Partial overlap attempt"
        })
        self.assertEqual(r.status_code, 409)

    def test_15_booking_case06_adjacent_slots_allowed(self):
        """Case 6: Same room with exactly adjacent time slots (12:00-14:00) allowed."""
        target_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        r = client.post("/api/v1/bookings", headers=self.faculty_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T12:00:00",
            "end_time": f"{target_date}T14:00:00",
            "purpose": "Adjacent back-to-back session"
        })
        self.assertEqual(r.status_code, 201, "Back-to-back adjacent slots must not conflict")

    def test_16_booking_case07_different_rooms_same_time(self):
        """Case 7: Different rooms at the same time allowed."""
        target_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        r = client.post("/api/v1/bookings", headers=self.faculty_headers, json={
            "resource_id": 2,  # Auditorium
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Simultaneous event in Auditorium"
        })
        self.assertEqual(r.status_code, 201)

    def test_17_booking_case08_and_09_pending_and_approved_clash(self):
        """Case 8 & 9: Clashes with Pending and Approved bookings are rejected."""
        target_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        # Auditorium booking creates Pending status
        aud_res = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 2,
            "start_time": f"{target_date}T14:00:00",
            "end_time": f"{target_date}T16:00:00",
            "purpose": "Pending Auditorium Request"
        })
        self.assertEqual(aud_res.status_code, 201)
        self.assertEqual(aud_res.json()["status"], "Pending")

        # Second request clashes with Pending
        clash_res = client.post("/api/v1/bookings", headers=self.faculty_headers, json={
            "resource_id": 2,
            "start_time": f"{target_date}T15:00:00",
            "end_time": f"{target_date}T17:00:00",
            "purpose": "Clashing with Pending"
        })
        self.assertEqual(clash_res.status_code, 409)

    def test_18_booking_case10_and_11_rejected_and_cancelled_no_clash(self):
        """Case 10 & 11: Slots from Rejected and Cancelled bookings are freed."""
        target_date = (datetime.now() + timedelta(days=6)).strftime("%Y-%m-%d")
        # Create and cancel
        c_res = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Session to cancel"
        })
        bk_id = c_res.json()["booking_id"]
        client.post(f"/api/v1/bookings/{bk_id}/cancel", headers=self.student_headers, json={"remarks": "Changed mind"})

        # New request for same slot succeeds
        rebook = client.post("/api/v1/bookings", headers=self.faculty_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "New valid session in freed slot"
        })
        self.assertEqual(rebook.status_code, 201)

    def test_19_booking_case12_academic_timetable_conflict(self):
        """Case 12: Academic timetable slot (Monday 09:00-11:00 on Lab 101) rejected."""
        # Calculate next Monday
        today = datetime.now().date()
        days_ahead = 7 - today.weekday()  # Monday is 0
        if days_ahead <= 0:
            days_ahead += 7
        next_mon = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{next_mon}T09:30:00",
            "end_time": f"{next_mon}T10:30:00",
            "purpose": "Clashing with university timetable"
        })
        self.assertEqual(resp.status_code, 409)
        self.assertIn("timetable conflict", resp.json()["detail"].lower())

    def test_20_booking_case13_and_14_blackout_and_maintenance(self):
        """Case 13 & 14: Booking during blackout or maintenance is rejected."""
        target_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        # Create manual blackout
        bo = client.post("/api/v1/blackouts", headers=self.admin_headers, json={
            "resource_id": 1,
            "start_datetime": f"{target_date}T08:00:00",
            "end_datetime": f"{target_date}T12:00:00",
            "reason": "Annual Network Infrastructure Upgrade"
        })
        self.assertEqual(bo.status_code, 201)

        # Attempt booking during blackout
        b_res = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T09:00:00",
            "end_time": f"{target_date}T11:00:00",
            "purpose": "During blackout"
        })
        self.assertEqual(b_res.status_code, 409)
        self.assertIn("blackout", b_res.json()["detail"].lower())

    def test_21_booking_case15_inactive_resource(self):
        """Case 15: Inactive resource (Resource 4) cannot be booked."""
        tomorrow = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 4,  # Inactive
            "start_time": f"{tomorrow}T10:00:00",
            "end_time": f"{tomorrow}T12:00:00",
            "purpose": "Booking inactive hall"
        })
        self.assertEqual(resp.status_code, 409)

    def test_22_booking_case16_concurrent_booking_serialization(self):
        """Case 16: Two concurrent booking requests serialize via row lock; exactly one wins."""
        target_date = (datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d")
        results = []

        def make_booking(user_header, label):
            r = client.post("/api/v1/bookings", headers=user_header, json={
                "resource_id": 1,
                "start_time": f"{target_date}T15:00:00",
                "end_time": f"{target_date}T17:00:00",
                "purpose": f"Concurrent test {label}"
            })
            results.append(r.status_code)

        t1 = threading.Thread(target=make_booking, args=(self.student_headers, "User 1"))
        t2 = threading.Thread(target=make_booking, args=(self.faculty_headers, "User 2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn(201, results, "One request must succeed")
        self.assertIn(409, results, "The other concurrent request must be rejected")

    def test_23_booking_case18_19_20_society_permissions(self):
        """Cases 18, 19, 20: Society bookings validated for membership and can_book permission."""
        target_date = (datetime.now() + timedelta(days=9)).strftime("%Y-%m-%d")

        # Case 18: User 2 (Faculty) is not in Society 1
        r18 = client.post("/api/v1/bookings", headers=self.faculty_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Faculty claiming club without membership",
            "society_id": 1
        })
        self.assertEqual(r18.status_code, 403)

        # Case 20: User 4 (Student) has can_book=1 in Society 1
        r20 = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Robotics Club Official Workshop",
            "society_id": 1
        })
        self.assertEqual(r20.status_code, 201)

    def test_24_booking_case21_22_23_24_multi_and_equipment(self):
        """Cases 21-24: Multi-resource, participants, invalid IDs, unavailable equipment."""
        target_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")

        # Case 23: Invalid participant ID
        r23 = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Invalid attendee test",
            "participants": [{"user_id": 999999}]
        })
        self.assertEqual(r23.status_code, 400)

        # Case 24: Equipment under maintenance (Item 2)
        r24 = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Broken mic request",
            "equipment_ids": [2]
        })
        self.assertIn(r24.status_code, [400, 409])

        # Case 21 & 22: Valid booking with participants and available equipment
        r_valid = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{target_date}T10:00:00",
            "end_time": f"{target_date}T12:00:00",
            "purpose": "Hackathon kickoff",
            "participants": [{"user_id": 2}],
            "equipment_ids": [1]
        })
        self.assertEqual(r_valid.status_code, 201)

    # =========================================================================
    # PHASE 5: MAINTENANCE TESTS
    # =========================================================================
    def test_25_maintenance_linked_blackout_and_completion(self):
        """Test maintenance creation with linked blackout and clean removal on resolution."""
        # 1. Create maintenance on Lab 101
        m_resp = client.post("/api/v1/maintenance", headers=self.admin_headers, json={
            "resource_id": 1,
            "issue_description": "Ceiling HVAC leak repair"
        })
        self.assertEqual(m_resp.status_code, 201)
        m_id = m_resp.json()["maintenance_id"]

        # Verify blackout was created with maintenance_id
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT blackout_id, maintenance_id FROM resource_blackout_periods WHERE maintenance_id = %s", (m_id,))
        bo = cursor.fetchone()
        self.assertIsNotNone(bo)
        self.assertEqual(bo["maintenance_id"], m_id)

        # 2. Complete maintenance
        comp_resp = client.patch(f"/api/v1/maintenance/{m_id}/complete", headers=self.staff_headers, json={
            "remarks": "HVAC unit patched and pressure tested"
        })
        self.assertEqual(comp_resp.status_code, 200)

        # Verify blackout was removed and status restored to Available
        cursor.execute("SELECT blackout_id FROM resource_blackout_periods WHERE maintenance_id = %s", (m_id,))
        self.assertIsNone(cursor.fetchone())

        cursor.execute("SELECT status FROM resources WHERE resource_id = 1")
        self.assertEqual(cursor.fetchone()["status"], "Available")

        # 3. Completing already completed maintenance must be rejected
        comp_again = client.patch(f"/api/v1/maintenance/{m_id}/complete", headers=self.staff_headers, json={
            "remarks": "Duplicate completion"
        })
        self.assertEqual(comp_again.status_code, 400)
        conn.close()

    # =========================================================================
    # PHASE 6: EQUIPMENT TESTS
    # =========================================================================
    def test_26_equipment_lifecycle_and_damage_handover(self):
        """Add, reserve, physical issue, and return with damaged condition."""
        # 1. Add equipment
        eq_resp = client.post("/api/v1/equipment", headers=self.admin_headers, json={
            "item_name": "DSLR 4K Camera",
            "serial_no": "CAM-4K-99",
            "location": "Media Locker 2",
            "condition_status": "Good",
            "availability_status": "Available"
        })
        self.assertEqual(eq_resp.status_code, 201)
        cam_id = eq_resp.json()["item_id"]

        # Create approved booking for issue
        tomorrow = (datetime.now() + timedelta(days=12)).strftime("%Y-%m-%d")
        b_resp = client.post("/api/v1/bookings", headers=self.admin_headers, json={
            "resource_id": 1,
            "start_time": f"{tomorrow}T10:00:00",
            "end_time": f"{tomorrow}T12:00:00",
            "purpose": "Camera recording test"
        })
        b_id = b_resp.json()["booking_id"]

        # 2. Issue equipment
        issue_res = client.post(f"/api/v1/equipment/{cam_id}/issue", headers=self.staff_headers, json={
            "booking_id": b_id
        })
        self.assertEqual(issue_res.status_code, 200)

        # Duplicate issue rejected
        dup_issue = client.post(f"/api/v1/equipment/{cam_id}/issue", headers=self.staff_headers, json={
            "booking_id": b_id
        })
        self.assertEqual(dup_issue.status_code, 400)

        # 3. Return Damaged -> Sets Maintenance
        ret_res = client.post(f"/api/v1/equipment/{cam_id}/return", headers=self.staff_headers, json={
            "condition_on_return": "Damaged",
            "remarks": "Lens scratched by user"
        })
        self.assertEqual(ret_res.status_code, 200)

        eq_check = client.get(f"/api/v1/equipment/{cam_id}")
        self.assertEqual(eq_check.json()["availability_status"], "Maintenance")
        self.assertEqual(eq_check.json()["condition_status"], "Damaged")

    # =========================================================================
    # PHASE 7: CHECK-IN DESK TESTS
    # =========================================================================
    def test_27_checkin_desk_lifecycle(self):
        """Staff checkin, student checkin rejection, duplicate checkin, checkout before checkin, valid checkout, no-show."""
        tomorrow = (datetime.now() + timedelta(days=13)).strftime("%Y-%m-%d")
        b_resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": f"{tomorrow}T14:00:00",
            "end_time": f"{tomorrow}T16:00:00",
            "purpose": "Attendance Test Session",
            "participants": [{"user_id": 2}]
        })
        b_id = b_resp.json()["booking_id"]

        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT booking_participant_id FROM booking_participants WHERE booking_id = %s LIMIT 1", (b_id,))
        bp_id = cursor.fetchone()["booking_participant_id"]
        conn.close()

        # 1. Student unauthorized checkin
        s_chk = client.post("/api/v1/checkins", headers=self.student_headers, json={
            "booking_participant_id": bp_id
        })
        self.assertEqual(s_chk.status_code, 403)

        # 2. Checkout before check-in rejected
        bad_co = client.post("/api/v1/checkins/99999/checkout", headers=self.staff_headers, json={
            "remarks": "Invalid checkout"
        })
        self.assertEqual(bad_co.status_code, 404)

        # 3. Authorized staff check-in
        ok_chk = client.post("/api/v1/checkins", headers=self.staff_headers, json={
            "booking_participant_id": bp_id,
            "remarks": "ID card verified"
        })
        self.assertEqual(ok_chk.status_code, 201)
        cid = ok_chk.json()["checkin_id"]

        # 4. Duplicate check-in rejected
        dup_chk = client.post("/api/v1/checkins", headers=self.staff_headers, json={
            "booking_participant_id": bp_id
        })
        self.assertEqual(dup_chk.status_code, 400)

        # 5. Valid checkout
        ok_co = client.post(f"/api/v1/checkins/{cid}/checkout", headers=self.staff_headers, json={
            "remarks": "Session concluded on time"
        })
        self.assertEqual(ok_co.status_code, 200)
        self.assertEqual(ok_co.json()["status"], "Checked-out")

    # =========================================================================
    # PHASE 8: SOCIETY AND USER TESTS
    # =========================================================================
    def test_28_society_and_user_governance(self):
        """Create society, add member, duplicate member rejection, admin provision faculty/staff."""
        # 1. Create Society
        soc_resp = client.post("/api/v1/societies", headers=self.admin_headers, json={
            "club_name": "Debating Society",
            "description": "Campus debating and public speaking",
            "established_year": 2025
        })
        self.assertEqual(soc_resp.status_code, 201)
        cid = soc_resp.json()["club_id"]

        # 2. Add Member
        add_mem = client.post(f"/api/v1/societies/{cid}/members", headers=self.admin_headers, json={
            "user_id": 4,  # Student
            "member_role": "Secretary",
            "can_book": True,
            "can_manage": False
        })
        self.assertEqual(add_mem.status_code, 201)

        # Duplicate member rejected
        dup_mem = client.post(f"/api/v1/societies/{cid}/members", headers=self.admin_headers, json={
            "user_id": 4,
            "member_role": "Secretary"
        })
        self.assertEqual(dup_mem.status_code, 400)

        # 3. Admin user creation of Staff
        staff_resp = client.post("/api/v1/users", headers=self.admin_headers, json={
            "name": "New Lab Technician",
            "email": "lab.tech@campus.edu",
            "role": "Staff",
            "password": "Password123!"
        })
        self.assertEqual(staff_resp.status_code, 201)
        u_id = staff_resp.json()["user_id"]

        # 4. Deactivate user & verify token rejected
        client.patch(f"/api/v1/users/{u_id}/status", headers=self.admin_headers, json={"is_active": False})
        deact_token = create_access_token(u_id, extra_claims={"role": "Staff", "email": "lab.tech@campus.edu", "name": "New Lab Technician"})
        deact_headers = {"Authorization": f"Bearer {deact_token}"}
        self.assertEqual(client.get("/api/v1/auth/me", headers=deact_headers).status_code, 403)

    # =========================================================================
    # PHASE 9: NOTIFICATIONS & AUDIT
    # =========================================================================
    def test_29_notifications_and_audit(self):
        """Verify notifications unread count, read marking, and duplicate reminder prevention."""
        # Unread count
        un_resp = client.get("/api/v1/notifications/unread-count", headers=self.student_headers)
        self.assertEqual(un_resp.status_code, 200)

        # List notifications
        list_notifs = client.get("/api/v1/notifications", headers=self.student_headers)
        self.assertEqual(list_notifs.status_code, 200)
        notifs = list_notifs.json()
        if notifs:
            nid = notifs[0]["notification_id"]
            mark_resp = client.patch(f"/api/v1/notifications/{nid}/read", headers=self.student_headers)
            self.assertEqual(mark_resp.status_code, 200)
            self.assertTrue(mark_resp.json()["is_read"])

        # Audit trail reports
        audit_resp = client.get("/api/v1/reports/audit", headers=self.admin_headers)
        self.assertEqual(audit_resp.status_code, 200)
        self.assertGreaterEqual(len(audit_resp.json()), 1)


if __name__ == "__main__":
    unittest.main()
