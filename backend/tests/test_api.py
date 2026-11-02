import sys
import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database.connection import get_connection_pool
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings

client = TestClient(app)


class SmartCampusComprehensiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pool = get_connection_pool()
        conn = pool.get_connection()
        cursor = conn.cursor(dictionary=True)

        # Retrieve an existing Admin user
        cursor.execute("SELECT user_id, email, role, name FROM users WHERE role = 'Admin' AND is_active = 1 LIMIT 1")
        admin = cursor.fetchone()

        if not admin:
            p_hash = get_password_hash("AdminPass123!")
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, role, is_active) VALUES ('Admin User', 'admin.auto@campus.edu', %s, 'Admin', 1)",
                (p_hash,)
            )
            admin_id = cursor.lastrowid
            admin_email = "admin.auto@campus.edu"
            admin_name = "Admin User"
        else:
            admin_id = admin["user_id"]
            admin_email = admin["email"]
            admin_name = admin["name"]

        # Retrieve or create a test Student user
        cursor.execute("SELECT user_id, email, role, name FROM users WHERE role = 'Student' AND is_active = 1 LIMIT 1")
        student = cursor.fetchone()
        if not student:
            p_hash = get_password_hash("StudentPass123!")
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, role, is_active) VALUES ('Test Student', 'student.test@campus.edu', %s, 'Student', 1)",
                (p_hash,)
            )
            student_id = cursor.lastrowid
            student_email = "student.test@campus.edu"
            student_name = "Test Student"
        else:
            student_id = student["user_id"]
            student_email = student["email"]
            student_name = student["name"]

        cursor.close()
        conn.close()

        cls.admin_id = admin_id
        cls.student_id = student_id

        cls.admin_token = create_access_token(
            subject=admin_id,
            extra_claims={"email": admin_email, "role": "Admin", "name": admin_name}
        )
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.student_token = create_access_token(
            subject=student_id,
            extra_claims={"email": student_email, "role": "Student", "name": student_name}
        )
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}

    def test_01_health_and_db_preservation(self):
        """Ensure system is healthy and original resources/timetables are preserved untouched."""
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healthy")

        res_resp = client.get("/api/v1/resources")
        self.assertEqual(res_resp.status_code, 200)
        self.assertGreaterEqual(len(res_resp.json()), 31, "Original 31 resources must be intact")

        tt_resp = client.get("/api/v1/timetable")
        self.assertEqual(tt_resp.status_code, 200)
        self.assertGreaterEqual(len(tt_resp.json()), 400, "Original timetable records must be intact")

    def test_02_public_registration_security(self):
        """Public registration must only allow Student role; reject Faculty/Staff/Admin."""
        # Attempt to register Faculty publicly -> Must be rejected (403 Forbidden)
        bad_resp = client.post("/api/v1/auth/register", json={
            "name": "Intruder Professor",
            "email": f"hacker_faculty_{int(datetime.now().timestamp())}@campus.edu",
            "password": "Password123!",
            "role": "Faculty"
        })
        self.assertIn(bad_resp.status_code, (400, 403), "Public registration of Faculty must be prohibited")

        # Public Student registration -> Must succeed
        test_email = f"student_new_{int(datetime.now().timestamp())}@campus.edu"
        ok_resp = client.post("/api/v1/auth/register", json={
            "name": "Public Registered Student",
            "email": test_email,
            "password": "Password123!",
            "role": "Student"
        })
        self.assertEqual(ok_resp.status_code, 201)
        self.assertEqual(ok_resp.json()["role"], "Student")

        # Clean up created test student
        pool = get_connection_pool()
        conn = pool.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE email = %s", (test_email,))
        conn.commit()
        c.close()
        conn.close()

    def test_03_token_revocation_on_logout(self):
        """Logging out must revoke token so it cannot be reused."""
        temp_token = create_access_token(
            subject=self.student_id,
            extra_claims={"email": "temp@campus.edu", "role": "Student", "name": "Temp"}
        )
        temp_headers = {"Authorization": f"Bearer {temp_token}"}

        # Request /auth/me -> Valid
        me_resp = client.get("/api/v1/auth/me", headers=temp_headers)
        self.assertEqual(me_resp.status_code, 200)

        # Logout -> Token gets revoked
        logout_resp = client.post("/api/v1/auth/logout", headers=temp_headers)
        self.assertEqual(logout_resp.status_code, 200)

        # Subsequent request with same token -> Must return 401
        post_me = client.get("/api/v1/auth/me", headers=temp_headers)
        self.assertEqual(post_me.status_code, 401, "Revoked token must be rejected with 401 Unauthorized")

    def test_04_midnight_booking_rejection(self):
        """Cross-midnight bookings must be explicitly rejected with a clear validation message."""
        resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": "2026-11-20T23:00:00",
            "end_time": "2026-11-21T01:00:00",
            "purpose": "Midnight hackathon session",
            "expected_participants": 5
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("midnight", resp.json()["detail"].lower())

    def test_05_maintenance_blackout_linking_and_foreign_key(self):
        """Maintenance creation links to blackout via maintenance_id FK (ON DELETE RESTRICT); completion removes blackout."""
        # 1. Create maintenance ticket
        m_resp = client.post("/api/v1/maintenance", headers=self.admin_headers, json={
            "resource_id": 7,
            "issue_description": "Projector optical alignment needed",
            "remarks": "Scheduled technical maintenance"
        })
        self.assertEqual(m_resp.status_code, 201)
        maint_id = m_resp.json()["maintenance_id"]

        pool = get_connection_pool()
        conn = pool.get_connection()
        c = conn.cursor(dictionary=True)

        # 2. Verify blackout record was automatically linked with maintenance_id
        c.execute("SELECT blackout_id, maintenance_id FROM resource_blackout_periods WHERE maintenance_id = %s", (maint_id,))
        bo = c.fetchone()
        self.assertIsNotNone(bo, "Blackout period must be automatically created and linked to maintenance_id")
        self.assertEqual(bo["maintenance_id"], maint_id)

        # 3. Test ON DELETE RESTRICT foreign key: Attempting to delete maintenance record directly while blackout references it must fail
        with self.assertRaises(Exception):
            c.execute("DELETE FROM maintenance_records WHERE maintenance_id = %s", (maint_id,))

        c.close()
        conn.close()

        # 4. Complete maintenance via API -> must resolve ticket and cleanly remove only its linked blackout
        comp_resp = client.patch(f"/api/v1/maintenance/{maint_id}/complete", headers=self.admin_headers, json={
            "remarks": "Optical alignment finished and tested"
        })
        self.assertEqual(comp_resp.status_code, 200)
        self.assertEqual(comp_resp.json()["status"], "Resolved")

        # Verify blackout was removed
        conn = pool.get_connection()
        c = conn.cursor(dictionary=True)
        c.execute("SELECT blackout_id FROM resource_blackout_periods WHERE maintenance_id = %s", (maint_id,))
        self.assertIsNone(c.fetchone(), "Completed maintenance must remove its linked blackout record")

        # Clean up maintenance ticket
        c.execute("DELETE FROM maintenance_records WHERE maintenance_id = %s", (maint_id,))
        conn.commit()
        c.close()
        conn.close()

    def test_06_equipment_physical_handover_and_damage_workflow(self):
        """Equipment reservation, physical handover (/issue), and return (/return) with condition checks."""
        pool = get_connection_pool()
        conn = pool.get_connection()
        c = conn.cursor(dictionary=True)

        # Clean any prior test mixer
        c.execute("DELETE FROM equipment_items WHERE serial_no LIKE 'SN-TEST-MIX%'")
        conn.commit()

        # Insert dedicated test equipment item
        test_sn = f"SN-TEST-MIX-{int(datetime.now().timestamp())}"
        c.execute(
            """
            INSERT INTO equipment_items (item_name, serial_no, location, condition_status, availability_status)
            VALUES ('Audio Mixer Unit Test', %s, 'Media Store', 'Good', 'Available')
            """,
            (test_sn,)
        )
        item_id = c.lastrowid
        conn.commit()
        c.close()
        conn.close()

        # Create a valid booking via API
        book_resp = client.post("/api/v1/bookings", headers=self.admin_headers, json={
            "resource_id": 1,
            "start_time": "2026-11-25T14:00:00",
            "end_time": "2026-11-25T16:00:00",
            "purpose": "Audio mixing test session",
            "expected_participants": 2
        })
        self.assertEqual(book_resp.status_code, 201)
        booking_id = book_resp.json()["booking_id"]

        # Ensure booking is Approved
        if book_resp.json()["status"] == "Pending":
            client.post(f"/api/v1/approvals/{booking_id}/approve", headers=self.admin_headers, json={
                "remarks": "Auto-approved for equipment testing"
            })

        try:
            # 1. Issue equipment to booking
            issue_resp = client.post(f"/api/v1/equipment/{item_id}/issue", headers=self.admin_headers, json={
                "booking_id": booking_id
            })
            self.assertEqual(issue_resp.status_code, 200)

            # Check status changed to Issued
            eq_get = client.get(f"/api/v1/equipment/{item_id}")
            self.assertEqual(eq_get.json()["availability_status"], "Issued")

            # 2. Return equipment with DAMAGED condition -> Must transition to Maintenance
            ret_resp = client.post(f"/api/v1/equipment/{item_id}/return", headers=self.admin_headers, json={
                "condition_on_return": "Damaged",
                "remarks": "Fader slider snapped during session",
                "booking_id": booking_id
            })
            self.assertEqual(ret_resp.status_code, 200)

            eq_damaged = client.get(f"/api/v1/equipment/{item_id}")
            self.assertEqual(eq_damaged.json()["availability_status"], "Maintenance")
            self.assertEqual(eq_damaged.json()["condition_status"], "Damaged")

        finally:
            # Cleanup test records
            conn = pool.get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM booking_equipment_items WHERE item_id = %s", (item_id,))
            c.execute("DELETE FROM maintenance_records WHERE item_id = %s", (item_id,))
            c.execute("DELETE FROM equipment_items WHERE item_id = %s", (item_id,))
            c.execute("DELETE FROM booking_participants WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM booking_resources WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM booking_approvals WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM booking_audit WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM bookings WHERE booking_id = %s", (booking_id,))
            conn.commit()
            c.close()
            conn.close()

    def test_equipment_only_reservation_uses_item_id(self):
        """Equipment-only reservations accept the documented item_id payload and persist the requested item."""
        pool = get_connection_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()
        serial_no = f"SN-TEST-BOOKING-{int(datetime.now().timestamp() * 1000)}"
        cursor.execute(
            """
            INSERT INTO equipment_items (item_name, serial_no, location, condition_status, availability_status)
            VALUES ('Equipment Booking Contract Test', %s, 'Unit Test Store', 'Good', 'Available')
            """,
            (serial_no,)
        )
        item_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()

        booking_id = None
        try:
            start = (datetime.now() + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
            response = client.post("/api/v1/bookings", headers=self.student_headers, json={
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(hours=2)).isoformat(),
                "purpose": "Equipment-only contract test",
                "equipment_requests": [{"item_id": item_id, "quantity": 1}]
            })
            self.assertEqual(response.status_code, 201, response.text)
            booking = response.json()
            booking_id = booking["booking_id"]
            self.assertEqual(booking["equipment"][0]["item_id"], item_id)
            self.assertEqual(booking["equipment"][0]["requested_quantity"], 1)
            self.assertEqual(booking["status"], "Pending")
            schedule_before_approval = client.get("/api/v1/bookings/my/schedule", headers=self.student_headers)
            self.assertEqual(schedule_before_approval.status_code, 200, schedule_before_approval.text)
            self.assertEqual(
                schedule_before_approval.json()["today"],
                datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)).date().isoformat()
            )
            self.assertNotIn(
                booking_id,
                [item["booking_id"] for item in schedule_before_approval.json()["upcoming_bookings"]]
            )

            approved = client.post(
                f"/api/v1/approvals/{booking_id}/approve",
                headers=self.admin_headers,
                json={"remarks": "Schedule API test approval"}
            )
            self.assertEqual(approved.status_code, 200, approved.text)
            pending = client.get("/api/v1/approvals/pending", headers=self.admin_headers)
            self.assertEqual(pending.status_code, 200, pending.text)
            self.assertNotIn(booking_id, [item["booking_id"] for item in pending.json()])

            schedule_after_approval = client.get("/api/v1/bookings/my/schedule", headers=self.student_headers)
            self.assertEqual(schedule_after_approval.status_code, 200, schedule_after_approval.text)
            approved_booking = next(
                item for item in schedule_after_approval.json()["upcoming_bookings"]
                if item["booking_id"] == booking_id
            )
            self.assertEqual(approved_booking["status"], "Approved")
            self.assertEqual(approved_booking["start_time"], start.isoformat())
            self.assertEqual(approved_booking["equipment"][0]["item_id"], item_id)

            cancelled = client.patch(
                f"/api/v1/bookings/{booking_id}/cancel",
                headers=self.student_headers,
                json={"remarks": "Schedule API test cleanup"}
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            schedule_after_cancellation = client.get("/api/v1/bookings/my/schedule", headers=self.student_headers)
            visible_ids = [
                item["booking_id"]
                for item in schedule_after_cancellation.json()["today_bookings"] +
                schedule_after_cancellation.json()["upcoming_bookings"]
            ]
            self.assertNotIn(booking_id, visible_ids)
        finally:
            conn = pool.get_connection()
            cursor = conn.cursor()
            if booking_id:
                cursor.execute("DELETE FROM notifications WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_participants WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_equipment_items WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_approvals WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_audit WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM bookings WHERE booking_id = %s", (booking_id,))
            cursor.execute("DELETE FROM equipment_items WHERE item_id = %s", (item_id,))
            conn.commit()
            cursor.close()
            conn.close()

    def test_07_system_audit_trail_sanitization(self):
        """System audit must log entity changes without exposing passwords or secret tokens."""
        pool = get_connection_pool()
        conn = pool.get_connection()
        c = conn.cursor(dictionary=True)

        # Trigger an Admin user creation
        test_email = f"staff_test_{int(datetime.now().timestamp())}@campus.edu"
        create_resp = client.post("/api/v1/users", headers=self.admin_headers, json={
            "name": "Test Staff Engineer",
            "email": test_email,
            "role": "Staff",
            "password": "SecurePassword123!"
        })
        self.assertEqual(create_resp.status_code, 201)
        created_user_id = create_resp.json()["user_id"]

        # Check system_audit table
        c.execute(
            "SELECT audit_id, entity_type, entity_id, action, new_values FROM system_audit WHERE entity_type = 'User' AND entity_id = %s ORDER BY audit_id DESC LIMIT 1",
            (created_user_id,)
        )
        audit_row = c.fetchone()
        self.assertIsNotNone(audit_row, "system_audit must record user creation")
        self.assertNotIn("password", str(audit_row["new_values"]).lower(), "Passwords must never be saved in audit log")
        self.assertNotIn("token", str(audit_row["new_values"]).lower(), "Tokens must never be saved in audit log")

        # Cleanup
        c.execute("DELETE FROM system_audit WHERE entity_type = 'User' AND entity_id = %s", (created_user_id,))
        c.execute("DELETE FROM users WHERE user_id = %s", (created_user_id,))
        conn.commit()
        c.close()
        conn.close()

    def test_08_duplicate_reminder_prevention(self):
        """Idempotent reminder service must prevent duplicate reminders for the same booking and user."""
        # Create an upcoming booking starting within the next 2 hours via API
        now = datetime.now()
        start = now + timedelta(minutes=50)
        end = now + timedelta(minutes=100)
        if start.date() != end.date():
            start = (now + timedelta(days=1)).replace(hour=0, minute=10, second=0, microsecond=0)
            end = start + timedelta(minutes=50)

        book_resp = client.post("/api/v1/bookings", headers=self.student_headers, json={
            "resource_id": 1,
            "start_time": start.strftime('%Y-%m-%dT%H:%M:%S'),
            "end_time": end.strftime('%Y-%m-%dT%H:%M:%S'),
            "purpose": "Reminder test session",
            "expected_participants": 1
        })
        self.assertEqual(book_resp.status_code, 201)
        booking_id = book_resp.json()["booking_id"]

        if book_resp.json()["status"] == "Pending":
            client.post(f"/api/v1/approvals/{booking_id}/approve", headers=self.admin_headers, json={
                "remarks": "Auto-approved for reminder test"
            })

        pool = get_connection_pool()
        conn = pool.get_connection()
        c = conn.cursor(dictionary=True)

        try:
            # 1. Trigger reminder service first time
            resp1 = client.post("/api/v1/notifications/send-reminders", headers=self.admin_headers)
            self.assertEqual(resp1.status_code, 200)

            # 2. Trigger reminder service second time (concurrent/consecutive execution)
            resp2 = client.post("/api/v1/notifications/send-reminders", headers=self.admin_headers)
            self.assertEqual(resp2.status_code, 200)

            # Count reminder notifications for this booking
            c.execute(
                "SELECT COUNT(*) as cnt FROM notifications WHERE booking_id = %s AND user_id = %s AND type = 'Reminder'",
                (booking_id, self.student_id)
            )
            count = c.fetchone()["cnt"]
            self.assertEqual(count, 1, "Duplicate reminder must be prevented; exactly 1 reminder sent")

        finally:
            c.execute("DELETE FROM notifications WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM booking_participants WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM booking_resources WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM booking_approvals WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM booking_audit WHERE booking_id = %s", (booking_id,))
            c.execute("DELETE FROM bookings WHERE booking_id = %s", (booking_id,))
            conn.commit()
            c.close()
            conn.close()

    def test_dashboard_date_range_and_runtime_settings(self):
        bookings_page = client.get(
            "/api/v1/bookings/page",
            headers=self.student_headers,
            params={"limit": 5, "sort_by": "created_desc"}
        )
        self.assertEqual(bookings_page.status_code, 200, bookings_page.text)
        self.assertLessEqual(len(bookings_page.json()["items"]), 5)
        self.assertGreaterEqual(bookings_page.json()["total"], len(bookings_page.json()["items"]))
        equipment_page = client.get(
            "/api/v1/bookings/page",
            headers=self.student_headers,
            params={"booking_type": "Equipment", "limit": 5}
        )
        self.assertEqual(equipment_page.status_code, 200, equipment_page.text)

        dashboard = client.get(
            "/api/v1/reports/dashboard",
            headers=self.admin_headers,
            params={"start_date": datetime.now().date().isoformat(), "end_date": datetime.now().date().isoformat()}
        )
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertIn("equipment_units", dashboard.json())
        self.assertIn("recent_activity", dashboard.json())

        settings_response = client.get("/api/v1/reports/settings", headers=self.admin_headers)
        self.assertEqual(settings_response.status_code, 200, settings_response.text)
        configured = settings_response.json()
        payload = {
            "academic_year": configured["academic_year"],
            "timetable_enforcement": configured["timetable_enforcement"],
            "booking_window_days": configured["booking_window_days"],
            "approval_mode": configured["approval_mode"],
            "approval_categories": configured["approval_categories"],
            "min_booking_minutes": configured["min_booking_minutes"],
            "max_booking_minutes": configured["max_booking_minutes"],
            "cancellation_cutoff_hours": configured["cancellation_cutoff_hours"]
        }
        pool = get_connection_pool()
        conn = pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT updated_by, updated_at FROM system_settings WHERE setting_id = 1")
        original_metadata = cursor.fetchone()
        cursor.execute("SELECT COALESCE(MAX(audit_id), 0) AS audit_id FROM system_audit WHERE entity_type = 'Settings' AND entity_id = 1")
        previous_audit_id = cursor.fetchone()["audit_id"]
        cursor.close()
        conn.close()
        try:
            saved = client.put("/api/v1/reports/settings", headers=self.admin_headers, json=payload)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["booking_window_days"], configured["booking_window_days"])
        finally:
            conn = pool.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE system_settings SET updated_by = %s, updated_at = %s WHERE setting_id = 1",
                (original_metadata["updated_by"], original_metadata["updated_at"])
            )
            cursor.execute(
                """
                DELETE FROM system_audit
                WHERE entity_type = 'Settings' AND entity_id = 1 AND audit_id > %s
                """,
                (previous_audit_id,)
            )
            conn.commit()
            cursor.close()
            conn.close()

    def test_09_admin_and_user_notification_feeds_are_separate(self):
        """Admins only see admin-feed notifications, while users only see their personal notifications."""
        pool = get_connection_pool()
        conn = pool.get_connection()
        c = conn.cursor(dictionary=True)
        marker = f"notification-feed-test-{int(datetime.now().timestamp() * 1000)}"
        messages = {
            "admin": f"{marker}-admin",
            "admin_user": f"{marker}-admin-user",
            "student": f"{marker}-student",
            "student_admin": f"{marker}-student-admin"
        }

        try:
            c.execute(
                """
                INSERT INTO notifications (user_id, message, type, audience, is_read)
                VALUES
                    (%s, %s, 'Alert', 'Admin', 0),
                    (%s, %s, 'Info', 'User', 0),
                    (%s, %s, 'Info', 'User', 0),
                    (%s, %s, 'Alert', 'Admin', 0)
                """,
                (
                    self.admin_id, messages["admin"],
                    self.admin_id, messages["admin_user"],
                    self.student_id, messages["student"],
                    self.student_id, messages["student_admin"]
                )
            )
            conn.commit()

            admin_notifications = client.get("/api/v1/notifications", headers=self.admin_headers)
            student_notifications = client.get("/api/v1/notifications", headers=self.student_headers)
            self.assertEqual(admin_notifications.status_code, 200)
            self.assertEqual(student_notifications.status_code, 200)

            admin_messages = {notification["message"] for notification in admin_notifications.json()}
            student_messages = {notification["message"] for notification in student_notifications.json()}
            self.assertIn(messages["admin"], admin_messages)
            self.assertNotIn(messages["admin_user"], admin_messages)
            self.assertIn(messages["student"], student_messages)
            self.assertNotIn(messages["student_admin"], student_messages)
        finally:
            c.execute(
                "DELETE FROM notifications WHERE message LIKE %s",
                (f"{marker}-%",)
            )
            conn.commit()
            c.close()
            conn.close()


if __name__ == "__main__":
    unittest.main()
