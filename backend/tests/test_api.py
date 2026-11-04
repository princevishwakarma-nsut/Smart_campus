import sys
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database.connection import get_connection_pool
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings
from app.core.permissions import UserContext
from app.schemas.blackout import BlackoutCreate
from app.database.transaction import transaction_scope
from app.api.v1.endpoints import blackouts as blackout_endpoint

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
            admin_feed = client.get("/api/v1/notifications", headers=self.admin_headers, params={"is_read": False})
            self.assertEqual(admin_feed.status_code, 200, admin_feed.text)
            admin_request_notification = next(
                item for item in admin_feed.json() if item["booking_id"] == booking_id
            )
            self.assertEqual(admin_request_notification["equipment_name"], "Equipment Booking Contract Test")
            self.assertIsNotNone(admin_request_notification["requester_name"])
            self.assertIn("Equipment Booking Contract Test", admin_request_notification["message"])
            student_feed = client.get("/api/v1/notifications", headers=self.student_headers, params={"is_read": False})
            self.assertIn(booking_id, [item["booking_id"] for item in student_feed.json()])
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
            self.assertEqual(approved_booking["equipment"][0]["issued_quantity"], 0)
            student_feed_after_approval = client.get(
                "/api/v1/notifications",
                headers=self.student_headers,
                params={"is_read": False}
            )
            self.assertTrue(any(
                item["booking_id"] == booking_id and "approved" in item["message"].lower()
                for item in student_feed_after_approval.json()
            ))

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
            admin_feed_after_cancel = client.get(
                "/api/v1/notifications",
                headers=self.admin_headers,
                params={"is_read": False}
            )
            self.assertTrue(any(
                item["booking_id"] == booking_id and "cancelled" in item["message"].lower()
                for item in admin_feed_after_cancel.json()
            ))
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

    def test_equipment_weekday_blackout_conflicts_and_blocks_booking(self):
        marker = f"equipment-blackout-{int(datetime.now().timestamp() * 1000)}"
        equipment = client.post(
            "/api/v1/equipment",
            headers=self.admin_headers,
            json={
                "item_name": marker,
                "item_code": marker,
                "category": "Other",
                "unit": "Piece",
                "total_quantity": 2,
                "location": "Test Store",
            },
        )
        self.assertEqual(equipment.status_code, 201, equipment.text)
        item_id = equipment.json()["item_id"]
        blackout_group_ids = []
        blackout_ids = []
        booking_id = None

        try:
            today = datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)).date()
            days_until_monday = (7 - today.weekday()) % 7
            if days_until_monday < 3:
                days_until_monday += 7
            monday = today + timedelta(days=days_until_monday)
            blackout_start = datetime.combine(monday, datetime.min.time()).replace(hour=9)
            blackout_end = datetime.combine(monday + timedelta(days=4), datetime.min.time()).replace(hour=11)
            booking_start = blackout_start + timedelta(minutes=30)
            booking_end = booking_start + timedelta(minutes=30)

            booking = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "start_time": booking_start.isoformat(),
                    "end_time": booking_end.isoformat(),
                    "purpose": f"{marker} pre-existing booking",
                    "equipment_requests": [{"item_id": item_id, "quantity": 1}],
                },
            )
            self.assertEqual(booking.status_code, 201, booking.text)
            booking_id = booking.json()["booking_id"]

            blackout_payload = {
                "equipment_ids": [item_id],
                "start_datetime": blackout_start.isoformat(),
                "end_datetime": blackout_end.isoformat(),
                "repeat_weekdays": [0, 1, 2, 3, 4],
                "reason_category": "Maintenance",
                "reason_explanation": f"{marker} equipment maintenance",
            }
            preview = client.post(
                "/api/v1/blackouts/equipment/conflicts",
                headers=self.admin_headers,
                json={key: value for key, value in blackout_payload.items() if key != "reason_category" and key != "reason_explanation"},
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["occurrence_count"], 5)
            self.assertEqual(preview.json()["conflict_count"], 1)

            rejected = client.post(
                "/api/v1/blackouts/equipment",
                headers=self.admin_headers,
                json=blackout_payload,
            )
            self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertTrue(rejected.json()["detail"]["confirmation_required"])

            created = client.post(
                "/api/v1/blackouts/equipment",
                headers=self.admin_headers,
                json={**blackout_payload, "confirm_booking_conflicts": True},
            )
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["occurrence_count"], 5)
            self.assertEqual(created.json()["equipment_count"], 1)
            blackout_group_ids.extend(created.json()["blackout_group_ids"])
            blackout_ids.extend(created.json()["blackout_ids"])

            existing_booking = client.get(
                f"/api/v1/bookings/{booking_id}",
                headers=self.student_headers,
            )
            self.assertEqual(existing_booking.status_code, 200, existing_booking.text)
            self.assertEqual(existing_booking.json()["status"], booking.json()["status"])

            blocked = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "start_time": booking_start.isoformat(),
                    "end_time": booking_end.isoformat(),
                    "purpose": f"{marker} blocked booking",
                    "equipment_requests": [{"item_id": item_id, "quantity": 1}],
                },
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertIn(f"{marker} equipment maintenance", blocked.json()["detail"])

            availability = client.get(
                f"/api/v1/equipment/{item_id}/availability",
                params={
                    "start_time": booking_start.isoformat(),
                    "end_time": booking_end.isoformat(),
                },
            )
            self.assertEqual(availability.status_code, 200, availability.text)
            self.assertEqual(availability.json()["available_quantity"], 0)
            self.assertEqual(availability.json()["blackout"]["reason_category"], "Maintenance")

            outside = client.get(
                f"/api/v1/equipment/{item_id}/availability",
                params={
                    "start_time": (monday + timedelta(days=5)).isoformat() + "T10:00:00",
                    "end_time": (monday + timedelta(days=5)).isoformat() + "T11:00:00",
                },
            )
            self.assertEqual(outside.status_code, 200, outside.text)
            self.assertEqual(outside.json()["available_quantity"], 2)

            listed = client.get("/api/v1/blackouts/equipment", headers=self.admin_headers)
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(
                len([row for row in listed.json() if row["blackout_group_id"] in blackout_group_ids]),
                5,
            )
            cancelled = client.patch(
                f"/api/v1/blackouts/equipment/{blackout_ids[0]}/cancel",
                headers=self.admin_headers,
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            self.assertEqual(cancelled.json()["cancelled_count"], 1)
        finally:
            conn = get_connection_pool().get_connection()
            cursor = conn.cursor()
            if booking_id:
                cursor.execute("DELETE FROM notifications WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_participants WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_equipment_items WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_approvals WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_audit WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM bookings WHERE booking_id = %s", (booking_id,))
            if blackout_ids:
                placeholders = ",".join(["%s"] * len(blackout_ids))
                cursor.execute(
                    f"DELETE FROM system_audit WHERE entity_type = 'EquipmentBlackout' AND entity_id IN ({placeholders})",
                    tuple(blackout_ids),
                )
            if blackout_group_ids:
                placeholders = ",".join(["%s"] * len(blackout_group_ids))
                cursor.execute(
                    f"DELETE FROM equipment_blackout_periods WHERE blackout_group_id IN ({placeholders})",
                    tuple(blackout_group_ids),
                )
            cursor.execute("DELETE FROM equipment_items WHERE item_id = %s", (item_id,))
            conn.commit()
            cursor.close()
            conn.close()

    def test_resource_weekday_blackout_expands_and_blocks_booking(self):
        marker = f"resource-weekday-blackout-{int(datetime.now().timestamp() * 1000)}"
        categories = client.get("/api/v1/categories")
        self.assertEqual(categories.status_code, 200, categories.text)
        category_id = categories.json()[0]["category_id"]
        created_resource = client.post(
            "/api/v1/resources",
            headers=self.admin_headers,
            json={
                "category_id": category_id,
                "resource_name": marker,
                "resource_code": marker,
                "location": "Blackout weekday test",
                "capacity": 12,
                "status": "Available",
            },
        )
        self.assertEqual(created_resource.status_code, 201, created_resource.text)
        resource_id = created_resource.json()["resource_id"]
        blackout_ids = []
        booking_ids = []

        try:
            today = datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)).date()
            days_until_monday = (7 - today.weekday()) % 7
            if days_until_monday < 3:
                days_until_monday += 7
            monday = today + timedelta(days=days_until_monday)
            blackout_start = datetime.combine(monday, datetime.min.time()).replace(hour=9)
            blackout_end = datetime.combine(monday + timedelta(days=4), datetime.min.time()).replace(hour=11)
            payload = {
                "resource_ids": [resource_id],
                "start_datetime": blackout_start.isoformat(),
                "end_datetime": blackout_end.isoformat(),
                "repeat_weekdays": [0, 1, 2, 3, 4],
                "reason_category": "Maintenance",
                "reason_explanation": f"{marker} weekday repair",
            }
            preview = client.post("/api/v1/blackouts/conflicts", headers=self.admin_headers, json=payload)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["occurrence_count"], 5)
            created = client.post("/api/v1/blackouts", headers=self.admin_headers, json=payload)
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["occurrence_count"], 5)
            self.assertEqual(created.json()["resource_count"], 1)
            blackout_ids.extend(created.json()["blackout_ids"])

            requested_start = datetime.combine(monday + timedelta(days=2), datetime.min.time()).replace(hour=9, minute=30)
            blocked = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_id,
                    "start_time": requested_start.isoformat(),
                    "end_time": (requested_start + timedelta(minutes=30)).isoformat(),
                    "purpose": f"{marker} blocked booking",
                },
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertIn(f"{marker} weekday repair", blocked.json()["detail"])
        finally:
            conn = get_connection_pool().get_connection()
            cursor = conn.cursor()
            if blackout_ids:
                placeholders = ",".join(["%s"] * len(blackout_ids))
                cursor.execute(
                    f"DELETE FROM system_audit WHERE entity_type = 'Blackout' AND entity_id IN ({placeholders})",
                    tuple(blackout_ids),
                )
                cursor.execute(
                    f"DELETE FROM resource_blackout_periods WHERE blackout_id IN ({placeholders})",
                    tuple(blackout_ids),
                )
            cursor.execute("DELETE FROM resource_features WHERE resource_id = %s", (resource_id,))
            cursor.execute("DELETE FROM resources WHERE resource_id = %s", (resource_id,))
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

            c.execute("SELECT notification_id FROM notifications WHERE message = %s", (messages["student"],))
            student_notification_id = c.fetchone()["notification_id"]
            c.execute("SELECT notification_id FROM notifications WHERE message = %s", (messages["admin"],))
            admin_notification_id = c.fetchone()["notification_id"]

            self.assertEqual(
                client.get("/api/v1/notifications", headers=self.student_headers, params={"is_read": False}).status_code,
                200
            )
            self.assertEqual(
                client.patch(f"/api/v1/notifications/{student_notification_id}/read", headers=self.admin_headers).status_code,
                404
            )
            self.assertEqual(
                client.patch(f"/api/v1/notifications/{student_notification_id}/read", headers=self.student_headers).status_code,
                200
            )
            unread = client.get(
                "/api/v1/notifications",
                headers=self.student_headers,
                params={"is_read": False}
            )
            history = client.get(
                "/api/v1/notifications",
                headers=self.student_headers,
                params={"is_read": True}
            )
            self.assertNotIn(messages["student"], {notification["message"] for notification in unread.json()})
            self.assertIn(messages["student"], {notification["message"] for notification in history.json()})
            c.execute(
                """
                INSERT INTO notifications (user_id, message, type, audience, is_read)
                VALUES (%s, %s, 'Info', 'User', 1), (%s, %s, 'Info', 'User', 1)
                """,
                (
                    self.student_id, f"{marker}-history-page-1",
                    self.student_id, f"{marker}-history-page-2"
                )
            )
            conn.commit()
            first_history_page = client.get(
                "/api/v1/notifications",
                headers=self.student_headers,
                params={"is_read": True, "limit": 1}
            )
            self.assertEqual(first_history_page.status_code, 200, first_history_page.text)
            first_notification_id = first_history_page.json()[0]["notification_id"]
            second_history_page = client.get(
                "/api/v1/notifications",
                headers=self.student_headers,
                params={"is_read": True, "limit": 1, "before_id": first_notification_id}
            )
            self.assertEqual(second_history_page.status_code, 200, second_history_page.text)
            self.assertEqual(len(second_history_page.json()), 1)
            self.assertLess(second_history_page.json()[0]["notification_id"], first_notification_id)
            self.assertEqual(
                client.patch(f"/api/v1/notifications/{admin_notification_id}/read", headers=self.admin_headers).status_code,
                200
            )
            self.assertEqual(
                client.patch(f"/api/v1/notifications/{admin_notification_id}/read", headers=self.admin_headers).status_code,
                200
            )
        finally:
            c.execute(
                "DELETE FROM notifications WHERE message LIKE %s",
                (f"{marker}-%",)
            )
            conn.commit()
            c.close()
            conn.close()

    def test_inventory_resource_hours_and_equipment_serial_persist(self):
        """Resource schedules and equipment asset tags persist through their separate APIs."""
        marker = f"inventory-test-{int(datetime.now().timestamp() * 1000)}"
        categories = client.get("/api/v1/categories")
        self.assertEqual(categories.status_code, 200, categories.text)
        category_id = categories.json()[0]["category_id"]
        resource_id = None
        item_id = None
        pool = get_connection_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()

        try:
            resource = client.post(
                "/api/v1/resources",
                headers=self.admin_headers,
                json={
                    "category_id": category_id,
                    "resource_name": f"{marker} Classroom",
                    "resource_code": f"R-{marker}",
                    "location": "North Block",
                    "operating_hours": "Mon-Fri 08:00-20:00",
                    "capacity": 40,
                    "status": "Available",
                    "features": ["Projector"]
                }
            )
            self.assertEqual(resource.status_code, 201, resource.text)
            resource_id = resource.json()["resource_id"]
            edited_resource = client.put(
                f"/api/v1/resources/{resource_id}",
                headers=self.admin_headers,
                json={"operating_hours": "Mon-Sat 09:00-18:00", "capacity": 45}
            )
            self.assertEqual(edited_resource.status_code, 200, edited_resource.text)
            self.assertEqual(edited_resource.json()["operating_hours"], "Mon-Sat 09:00-18:00")
            self.assertEqual(edited_resource.json()["capacity"], 45)

            equipment = client.post(
                "/api/v1/equipment",
                headers=self.admin_headers,
                json={
                    "item_name": f"{marker} Microphone",
                    "item_code": f"EQ-{marker}",
                    "serial_no": f"S-{marker}",
                    "category": "Audio/Visual",
                    "unit": "Piece",
                    "total_quantity": 2,
                    "location": "Media Store"
                }
            )
            self.assertEqual(equipment.status_code, 201, equipment.text)
            item_id = equipment.json()["item_id"]
            self.assertEqual(equipment.json()["serial_no"], f"S-{marker}")
            edited_equipment = client.put(
                f"/api/v1/equipment/{item_id}",
                headers=self.admin_headers,
                json={"serial_no": f"S2-{marker}", "location": "AV Cabinet"}
            )
            self.assertEqual(edited_equipment.status_code, 200, edited_equipment.text)
            self.assertEqual(edited_equipment.json()["serial_no"], f"S2-{marker}")
            self.assertEqual(edited_equipment.json()["location"], "AV Cabinet")
        finally:
            if resource_id:
                cursor.execute("DELETE FROM resource_features WHERE resource_id = %s", (resource_id,))
                cursor.execute("DELETE FROM resources WHERE resource_id = %s", (resource_id,))
            if item_id:
                cursor.execute("DELETE FROM equipment_stock_movements WHERE item_id = %s", (item_id,))
                cursor.execute("DELETE FROM equipment_items WHERE item_id = %s", (item_id,))
            conn.commit()
            cursor.close()
            conn.close()

    def test_bulk_blackouts_conflicts_reason_edit_cancel_and_rollback(self):
        """Bulk category/resource selection is atomic and blackout reasons reach booking errors."""
        marker = f"blackout-bulk-{int(datetime.now().timestamp() * 1000)}"
        categories = client.get("/api/v1/categories")
        self.assertEqual(categories.status_code, 200, categories.text)
        category_ids = [row["category_id"] for row in categories.json()]
        self.assertGreaterEqual(len(category_ids), 2, "Bulk selection test needs two configured categories.")

        resource_ids = []
        booking_id = None
        booking_ids = []
        extra_admin_id = None
        blackout_group_ids = []
        blackout_ids = []
        start = (datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)) + timedelta(days=12)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        outside_booking = start.replace(hour=13)
        bulk_start = (datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)) + timedelta(days=365)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )

        try:
            notification_conn = get_connection_pool().get_connection()
            notification_cursor = notification_conn.cursor()
            notification_cursor.execute(
                """
                INSERT INTO users (name, email, password_hash, role, is_active)
                VALUES (%s, %s, %s, 'Admin', 1)
                """,
                (
                    f"{marker} Admin",
                    f"{marker}@campus.edu",
                    get_password_hash("BlackoutTestPass123!"),
                ),
            )
            extra_admin_id = notification_cursor.lastrowid
            notification_conn.commit()
            notification_cursor.close()
            notification_conn.close()

            for index, category_id in enumerate((category_ids[0], category_ids[0], category_ids[1])):
                response = client.post(
                    "/api/v1/resources",
                    headers=self.admin_headers,
                    json={
                        "category_id": category_id,
                        "resource_name": f"{marker} Resource {index}",
                        "resource_code": f"BR-{marker[-8:]}-{index}",
                        "location": "Blackout Test Block",
                        "capacity": 20,
                        "status": "Available",
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                resource_ids.append(response.json()["resource_id"])
            for index in range(41):
                response = client.post(
                    "/api/v1/resources",
                    headers=self.admin_headers,
                    json={
                        "category_id": category_ids[index % 2],
                        "resource_name": f"{marker} Bulk Resource {index + 3}",
                        "resource_code": f"BR-{marker[-7:]}-{index + 3}",
                        "location": "Blackout Test Block",
                        "capacity": 20,
                        "status": "Available",
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                resource_ids.append(response.json()["resource_id"])

            first_booking = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_ids[0],
                    "start_time": start.isoformat(),
                    "end_time": (start + timedelta(hours=1)).isoformat(),
                    "purpose": f"{marker} conflict booking",
                },
            )
            self.assertEqual(first_booking.status_code, 201, first_booking.text)
            booking_id = first_booking.json()["booking_id"]
            booking_ids.append(booking_id)

            conflict_payload = {
                "resource_ids": [resource_ids[0]],
                "category_ids": [],
                "start_datetime": start.isoformat(),
                "end_datetime": (start + timedelta(hours=2)).isoformat(),
            }
            invalid_blackout_date = client.post(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                json={
                    **conflict_payload,
                    "start_datetime": start.isoformat(),
                    "end_datetime": start.isoformat(),
                    "reason_category": "Maintenance",
                    "reason_explanation": f"{marker} invalid date range",
                },
            )
            self.assertEqual(invalid_blackout_date.status_code, 422, invalid_blackout_date.text)
            missing_blackout_reason = client.post(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                json={
                    **conflict_payload,
                    "reason_category": "Maintenance",
                },
            )
            self.assertEqual(missing_blackout_reason.status_code, 422, missing_blackout_reason.text)
            preview = client.post(
                "/api/v1/blackouts/conflicts",
                headers=self.admin_headers,
                json=conflict_payload,
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["conflict_count"], 1)
            self.assertTrue(preview.json()["conflicts"][0]["requester_name"])
            notification_conn = get_connection_pool().get_connection()
            notification_cursor = notification_conn.cursor(dictionary=True)
            notification_cursor.execute(
                """
                SELECT notification_id, message FROM notifications
                WHERE user_id = %s AND booking_id = %s AND audience = 'Admin'
                  AND message LIKE %s
                """,
                (extra_admin_id, booking_id, f"%{marker}%"),
            )
            self.assertTrue(notification_cursor.fetchall())
            notification_cursor.close()
            notification_conn.close()
            rejected_creation = client.post(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                json={
                    **conflict_payload,
                    "reason_category": "Maintenance",
                    "reason_explanation": f"{marker} projector maintenance",
                },
            )
            self.assertEqual(rejected_creation.status_code, 409, rejected_creation.text)
            self.assertEqual(len(rejected_creation.json()["detail"]["conflicts"]), 1)
            self.assertTrue(rejected_creation.json()["detail"]["confirmation_required"])
            confirmed_creation = client.post(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                json={
                    **conflict_payload,
                    "reason_category": "Maintenance",
                    "reason_explanation": f"{marker} confirmed projector maintenance",
                    "confirm_booking_conflicts": True,
                },
            )
            self.assertEqual(confirmed_creation.status_code, 201, confirmed_creation.text)
            self.assertEqual(confirmed_creation.json()["resource_count"], 1)
            blackout_group_ids.append(confirmed_creation.json()["blackout_group_id"])
            blackout_ids.extend(confirmed_creation.json()["blackout_ids"])
            booking_after_confirmation = client.get(
                f"/api/v1/bookings/{booking_id}",
                headers=self.student_headers,
            )
            self.assertEqual(booking_after_confirmation.status_code, 200, booking_after_confirmation.text)
            self.assertEqual(booking_after_confirmation.json()["status"], first_booking.json()["status"])
            notification_conn = get_connection_pool().get_connection()
            notification_cursor = notification_conn.cursor(dictionary=True)
            notification_cursor.execute(
                """
                SELECT notification_id, message FROM notifications
                WHERE user_id = %s AND booking_id = %s AND audience = 'User'
                  AND message LIKE %s
                """,
                (self.student_id, booking_id, "%confirmed projector maintenance%"),
            )
            self.assertTrue(notification_cursor.fetchall())
            notification_cursor.close()
            notification_conn.close()
            cancelled_blackout = client.patch(
                f"/api/v1/blackouts/{confirmed_creation.json()['blackout_id']}/cancel",
                headers=self.admin_headers,
            )
            self.assertEqual(cancelled_blackout.status_code, 200, cancelled_blackout.text)

            cancelled = client.patch(
                f"/api/v1/bookings/{booking_id}/cancel",
                headers=self.student_headers,
                json={"remarks": "Blackout conflict test cleanup"},
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            booking_id = None

            blackout_start = start.replace(hour=10)
            blackout_end = start.replace(hour=12)
            reason = f"{marker} projector maintenance"
            individual_payload = {
                "resource_ids": [resource_ids[0]],
                "excluded_resource_ids": [],
                "category_ids": [],
                "start_datetime": blackout_start.isoformat(),
                "end_datetime": blackout_end.isoformat(),
                "reason_category": "Maintenance",
                "reason_explanation": reason,
            }
            created = client.post(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                json=individual_payload,
            )
            self.assertEqual(created.status_code, 201, created.text)
            blackout_group_ids.append(created.json()["blackout_group_id"])
            blackout_ids.extend(created.json()["blackout_ids"])

            overlap = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_ids[0],
                    "start_time": start.replace(minute=30).isoformat(),
                    "end_time": start.replace(hour=11, minute=30).isoformat(),
                    "purpose": f"{marker} overlapping booking",
                },
            )
            self.assertEqual(overlap.status_code, 409, overlap.text)
            detail = overlap.json()["detail"]
            self.assertIn(f"{marker} Resource 0", detail)
            self.assertIn("Reason category: Maintenance", detail)
            self.assertIn(reason, detail)
            self.assertIn("overlapping blackout period", detail)

            outside = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_ids[0],
                    "start_time": outside_booking.isoformat(),
                    "end_time": (outside_booking + timedelta(hours=1)).isoformat(),
                    "purpose": f"{marker} outside blackout",
                },
            )
            self.assertEqual(outside.status_code, 201, outside.text)
            booking_id = outside.json()["booking_id"]
            booking_ids.append(booking_id)

            category_payload = {
                "resource_ids": [resource_ids[0], resource_ids[2], resource_ids[0]],
                "excluded_resource_ids": [resource_ids[1]],
                "category_ids": category_ids[:2],
                "start_datetime": bulk_start.isoformat(),
                "end_datetime": (bulk_start + timedelta(hours=3)).isoformat(),
            }
            bulk_preview = client.post(
                "/api/v1/blackouts/conflicts",
                headers=self.admin_headers,
                json=category_payload,
            )
            self.assertEqual(bulk_preview.status_code, 200, bulk_preview.text)
            selected = [row["resource_id"] for row in bulk_preview.json()["resources"]]
            self.assertEqual(len(selected), len(set(selected)))
            self.assertIn(resource_ids[0], selected)
            self.assertIn(resource_ids[2], selected)
            self.assertNotIn(resource_ids[1], selected)
            self.assertEqual(bulk_preview.json()["conflict_count"], 0)

            group_create = client.post(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                json={
                    **category_payload,
                    "reason_category": "University Examination",
                    "reason_explanation": f"{marker} exam period",
                },
            )
            self.assertEqual(group_create.status_code, 201, group_create.text)
            self.assertEqual(group_create.json()["resource_count"], len(selected))
            group_id = group_create.json()["blackout_group_id"]
            blackout_group_ids.append(group_id)
            blackout_ids.extend(group_create.json()["blackout_ids"])

            all_resources_payload = {
                "resource_ids": resource_ids,
                "category_ids": [],
                "start_datetime": (bulk_start + timedelta(days=10)).isoformat(),
                "end_datetime": (bulk_start + timedelta(days=10, hours=2)).isoformat(),
                "reason_category": "Cleaning",
                "reason_explanation": f"{marker} all 44 resource blackout",
            }
            all_resources_created = client.post(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                json=all_resources_payload,
            )
            self.assertEqual(all_resources_created.status_code, 201, all_resources_created.text)
            self.assertEqual(all_resources_created.json()["resource_count"], 44)
            self.assertEqual(len(set(all_resources_created.json()["blackout_ids"])), 44)
            blackout_group_ids.append(all_resources_created.json()["blackout_group_id"])
            blackout_ids.extend(all_resources_created.json()["blackout_ids"])
            verification_conn = get_connection_pool().get_connection()
            verification_cursor = verification_conn.cursor(dictionary=True)
            verification_cursor.execute(
                "SELECT COUNT(*) AS count FROM resource_blackout_periods WHERE blackout_group_id = %s",
                (all_resources_created.json()["blackout_group_id"],),
            )
            self.assertEqual(verification_cursor.fetchone()["count"], 44)
            verification_cursor.close()
            verification_conn.close()
            persisted_group = client.get(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                params={"status": "Active"},
            )
            self.assertEqual(persisted_group.status_code, 200, persisted_group.text)
            self.assertEqual(
                len([
                    row for row in persisted_group.json()
                    if row["blackout_group_id"] == all_resources_created.json()["blackout_group_id"]
                ]),
                44,
            )

            pool = get_connection_pool()
            conn = pool.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT blackout_id, resource_id, status FROM resource_blackout_periods WHERE blackout_group_id = %s",
                (group_id,),
            )
            group_rows = cursor.fetchall()
            self.assertEqual(len(group_rows), len(selected))
            self.assertEqual(len({row["resource_id"] for row in group_rows}), len(selected))
            listed_group = client.get(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                params={"status": "Active"},
            )
            self.assertEqual(listed_group.status_code, 200, listed_group.text)
            listed_items = [
                row for row in listed_group.json()
                if row["blackout_group_id"] == group_id
            ]
            self.assertEqual(len(listed_items), len(selected))
            self.assertEqual(listed_items[0]["reason_category"], "University Examination")
            self.assertEqual(listed_items[0]["category_ids"], category_ids[:2])
            self.assertEqual(listed_items[0]["excluded_resource_ids"], [resource_ids[1]])

            update_payload = {
                **category_payload,
                "reason_category": "Official Function",
                "reason_explanation": f"{marker} updated function schedule",
            }
            edited = client.put(
                f"/api/v1/blackouts/{group_rows[0]['blackout_id']}",
                headers=self.admin_headers,
                json=update_payload,
            )
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()["resource_count"], len(selected))
            cursor.execute(
                "SELECT blackout_id, reason_category, reason_explanation FROM resource_blackout_periods WHERE blackout_group_id = %s AND status = 'Active'",
                (group_id,),
            )
            updated_rows = cursor.fetchall()
            self.assertEqual({row["blackout_id"] for row in updated_rows}, {row["blackout_id"] for row in group_rows})
            self.assertTrue(all(row["reason_category"] == "Official Function" for row in updated_rows))

            canceled_group = client.patch(
                f"/api/v1/blackouts/{group_rows[0]['blackout_id']}/cancel",
                headers=self.admin_headers,
            )
            self.assertEqual(canceled_group.status_code, 200, canceled_group.text)
            cursor.execute(
                "SELECT COUNT(*) AS count FROM resource_blackout_periods WHERE blackout_group_id = %s AND status = 'Cancelled'",
                (group_id,),
            )
            self.assertEqual(cursor.fetchone()["count"], len(selected))
            history = client.get(
                "/api/v1/blackouts",
                headers=self.admin_headers,
                params={"status": "Cancelled"},
            )
            self.assertEqual(history.status_code, 200, history.text)
            self.assertEqual(
                len([row for row in history.json() if row["blackout_group_id"] == group_id]),
                len(selected),
            )
            cursor.close()
            conn.close()

            rollback_payload = BlackoutCreate(
                resource_ids=resource_ids,
                category_ids=[],
                start_datetime=(bulk_start + timedelta(days=1)),
                end_datetime=(bulk_start + timedelta(days=1, hours=1)),
                reason_category="Cleaning",
                reason_explanation=f"{marker} rollback",
            )
            original_scope = blackout_endpoint.transaction_scope

            @contextmanager
            def failing_transaction_scope():
                insert_count = 0
                with original_scope() as (transaction_conn, transaction_cursor):
                    class FailingCursor:
                        def execute(self, query, params=None):
                            nonlocal insert_count
                            if "INSERT INTO resource_blackout_periods" in query:
                                insert_count += 1
                                if insert_count == 2:
                                    raise RuntimeError("Injected second-resource failure")
                            return transaction_cursor.execute(query, params or ())

                        def __getattr__(self, name):
                            return getattr(transaction_cursor, name)

                    yield transaction_conn, FailingCursor()

            with mock.patch.object(blackout_endpoint, "transaction_scope", failing_transaction_scope):
                with self.assertRaisesRegex(RuntimeError, "Injected second-resource failure"):
                    blackout_endpoint.create_blackout(
                        rollback_payload,
                        UserContext(self.admin_id, "admin.test@campus.edu", "Admin", "Test Admin"),
                    )

            conn = get_connection_pool().get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT COUNT(*) AS count FROM resource_blackout_periods WHERE reason_explanation = %s",
                (f"{marker} rollback",),
            )
            self.assertEqual(cursor.fetchone()["count"], 0)
            cursor.close()
            conn.close()
        finally:
            conn = get_connection_pool().get_connection()
            cursor = conn.cursor()
            for created_booking_id in booking_ids:
                cursor.execute("DELETE FROM notifications WHERE booking_id = %s", (created_booking_id,))
                cursor.execute("DELETE FROM booking_participants WHERE booking_id = %s", (created_booking_id,))
                cursor.execute("DELETE FROM booking_equipment_items WHERE booking_id = %s", (created_booking_id,))
                cursor.execute("DELETE FROM booking_approvals WHERE booking_id = %s", (created_booking_id,))
                cursor.execute("DELETE FROM booking_audit WHERE booking_id = %s", (created_booking_id,))
                cursor.execute("DELETE FROM booking_resources WHERE booking_id = %s", (created_booking_id,))
                cursor.execute("DELETE FROM bookings WHERE booking_id = %s", (created_booking_id,))
            if blackout_ids:
                placeholders = ",".join(["%s"] * len(blackout_ids))
                cursor.execute(
                    f"DELETE FROM system_audit WHERE entity_type = 'Blackout' AND entity_id IN ({placeholders})",
                    tuple(blackout_ids),
                )
            if blackout_group_ids:
                placeholders = ",".join(["%s"] * len(blackout_group_ids))
                cursor.execute(
                    f"DELETE FROM resource_blackout_periods WHERE blackout_group_id IN ({placeholders})",
                    tuple(blackout_group_ids),
                )
            if resource_ids:
                placeholders = ",".join(["%s"] * len(resource_ids))
                cursor.execute(f"DELETE FROM resource_features WHERE resource_id IN ({placeholders})", tuple(resource_ids))
                cursor.execute(f"DELETE FROM resources WHERE resource_id IN ({placeholders})", tuple(resource_ids))
                cursor.execute("DELETE FROM notifications WHERE message LIKE %s", (f"%{marker}%",))
            if extra_admin_id:
                cursor.execute("DELETE FROM notifications WHERE user_id = %s", (extra_admin_id,))
                cursor.execute("DELETE FROM users WHERE user_id = %s", (extra_admin_id,))
            conn.commit()
            cursor.close()
            conn.close()

    def test_bulk_operating_hours_combines_categories_and_individual_resources(self):
        """A single schedule operation combines category and individual selections without duplicates."""
        marker = f"hours-bulk-{int(datetime.now().timestamp() * 1000)}"
        category_ids = []
        resource_ids = []
        pool = get_connection_pool()
        try:
            for suffix in ("A", "B"):
                category = client.post(
                    "/api/v1/categories",
                    headers=self.admin_headers,
                    json={"category_name": f"{marker} {suffix}", "description": "Temporary integration-test category"},
                )
                self.assertEqual(category.status_code, 201, category.text)
                category_ids.append(category.json()["category_id"])

            for index, category_id in enumerate((category_ids[0], category_ids[0], category_ids[1])):
                resource = client.post(
                    "/api/v1/resources",
                    headers=self.admin_headers,
                    json={
                        "category_id": category_id,
                        "resource_name": f"{marker} Resource {index}",
                        "resource_code": f"HB-{marker[-9:]}-{index}",
                        "location": "Operating Hours Bulk Test",
                        "capacity": 10,
                        "status": "Available",
                    },
                )
                self.assertEqual(resource.status_code, 201, resource.text)
                resource_ids.append(resource.json()["resource_id"])

            update = client.put(
                "/api/v1/resources/operating-hours/bulk",
                headers=self.admin_headers,
                json={
                    "category_ids": [category_ids[0]],
                    "resource_ids": [resource_ids[0], resource_ids[2]],
                    "weekdays": ["Monday"],
                    "closed_days": ["Tuesday"],
                    "open_time": "08:00",
                    "close_time": "18:00",
                },
            )
            self.assertEqual(update.status_code, 200, update.text)
            self.assertEqual(update.json()["resource_count"], 3)
            self.assertEqual(
                {item["resource_id"] for item in update.json()["resources"]},
                set(resource_ids),
            )

            conn = pool.get_connection()
            cursor = conn.cursor()
            try:
                placeholders = ",".join(["%s"] * len(resource_ids))
                cursor.execute(
                    f"SELECT DISTINCT resource_id FROM resource_operating_hours WHERE resource_id IN ({placeholders})",
                    tuple(resource_ids),
                )
                self.assertEqual({row[0] for row in cursor.fetchall()}, set(resource_ids))
            finally:
                cursor.close()
                conn.close()
        finally:
            if resource_ids or category_ids:
                conn = pool.get_connection()
                cursor = conn.cursor()
                try:
                    if resource_ids:
                        placeholders = ",".join(["%s"] * len(resource_ids))
                        cursor.execute(
                            f"DELETE FROM system_audit WHERE entity_type = 'ResourceOperatingHours' AND entity_id IN ({placeholders})",
                            tuple(resource_ids),
                        )
                        cursor.execute(
                            f"DELETE FROM resource_operating_hours WHERE resource_id IN ({placeholders})",
                            tuple(resource_ids),
                        )
                        cursor.execute(
                            f"DELETE FROM resource_features WHERE resource_id IN ({placeholders})",
                            tuple(resource_ids),
                        )
                        cursor.execute(f"DELETE FROM resources WHERE resource_id IN ({placeholders})", tuple(resource_ids))
                    if category_ids:
                        placeholders = ",".join(["%s"] * len(category_ids))
                        cursor.execute(f"DELETE FROM categories WHERE category_id IN ({placeholders})", tuple(category_ids))
                    conn.commit()
                finally:
                    cursor.close()
                    conn.close()

    def test_operating_hours_booking_overlaps_and_concurrent_users(self):
        """Exercise recurring hours, overlap boundaries, and resource-row concurrency against MySQL."""
        marker = f"hours-race-{int(datetime.now().timestamp() * 1000)}"
        categories = client.get("/api/v1/categories")
        self.assertEqual(categories.status_code, 200, categories.text)
        category_id = categories.json()[0]["category_id"]
        resource = client.post(
            "/api/v1/resources",
            headers=self.admin_headers,
            json={
                "category_id": category_id,
                "resource_name": f"{marker} Room",
                "resource_code": f"OH-{marker[-10:]}",
                "location": "Operating Hours Test Block",
                "capacity": 20,
                "status": "Available",
            },
        )
        self.assertEqual(resource.status_code, 201, resource.text)
        resource_id = resource.json()["resource_id"]
        second_user_id = None
        booking_ids = []
        exception_ids = []
        pool = get_connection_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO users (name, email, password_hash, role, is_active)
                VALUES (%s, %s, %s, 'Student', 1)
                """,
                (f"{marker} Student B", f"{marker}@campus.edu", get_password_hash("HoursRacePass123!")),
            )
            second_user_id = cursor.lastrowid
            conn.commit()
            second_token = create_access_token(
                subject=second_user_id,
                extra_claims={"email": f"{marker}@campus.edu", "role": "Student", "name": f"{marker} Student B"},
            )
            second_headers = {"Authorization": f"Bearer {second_token}"}

            all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            update = client.put(
                "/api/v1/resources/operating-hours/bulk",
                headers=self.admin_headers,
                json={
                    "resource_ids": [resource_id, resource_id],
                    "weekdays": all_days,
                    "closed_days": [],
                    "open_time": "08:00",
                    "close_time": "18:00",
                },
            )
            self.assertEqual(update.status_code, 200, update.text)
            self.assertEqual(update.json()["resource_count"], 1)

            campus_now = datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)).replace(tzinfo=None)
            target_date = (campus_now + timedelta(days=5)).date()

            def submit(headers, start, end, purpose):
                return client.post(
                    "/api/v1/bookings",
                    headers=headers,
                    json={
                        "resource_id": resource_id,
                        "start_time": f"{target_date.isoformat()}T{start}:00",
                        "end_time": f"{target_date.isoformat()}T{end}:00",
                        "purpose": f"{marker} {purpose}",
                    },
                )

            for start, end in (("09:00", "10:00"), ("17:00", "18:00")):
                allowed = submit(self.student_headers, start, end, "within operating hours")
                self.assertEqual(allowed.status_code, 201, allowed.text)
                booking_ids.append(allowed.json()["booking_id"])

            for start, end in (("07:00", "08:00"), ("18:30", "19:30")):
                outside = submit(self.student_headers, start, end, "outside operating hours")
                self.assertEqual(outside.status_code, 409, outside.text)
                self.assertIn("operating hours", outside.json()["detail"].lower())

            first = submit(self.student_headers, "10:00", "12:00", "overlap baseline")
            self.assertEqual(first.status_code, 201, first.text)
            booking_ids.append(first.json()["booking_id"])
            for start, end in (
                ("10:00", "12:00"),
                ("09:00", "11:00"),
                ("11:00", "13:00"),
                ("10:30", "11:30"),
                ("09:00", "13:00"),
            ):
                overlap = submit(second_headers, start, end, "overlap attempt")
                self.assertEqual(overlap.status_code, 409, overlap.text)
                self.assertIn("already reserved", overlap.json()["detail"])
                self.assertNotIn(f"{marker} Student", overlap.json()["detail"])

            adjacent = submit(second_headers, "12:00", "14:00", "adjacent reservation")
            self.assertEqual(adjacent.status_code, 201, adjacent.text)
            booking_ids.append(adjacent.json()["booking_id"])

            closed_date = target_date + timedelta(days=1)
            closed_weekday = closed_date.strftime("%A")
            weekly_closed = client.put(
                "/api/v1/resources/operating-hours/bulk",
                headers=self.admin_headers,
                json={
                    "resource_ids": [resource_id],
                    "weekdays": [day for day in all_days if day != closed_weekday],
                    "closed_days": [closed_weekday],
                    "open_time": "08:00",
                    "close_time": "18:00",
                },
            )
            self.assertEqual(weekly_closed.status_code, 200, weekly_closed.text)
            closed_day_booking = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_id,
                    "start_time": f"{closed_date.isoformat()}T09:00:00",
                    "end_time": f"{closed_date.isoformat()}T10:00:00",
                    "purpose": f"{marker} closed weekday",
                },
            )
            self.assertEqual(closed_day_booking.status_code, 409, closed_day_booking.text)
            self.assertIn("closed", closed_day_booking.json()["detail"].lower())

            weekly_open = client.put(
                "/api/v1/resources/operating-hours/bulk",
                headers=self.admin_headers,
                json={
                    "resource_ids": [resource_id],
                    "weekdays": all_days,
                    "closed_days": [],
                    "open_time": "08:00",
                    "close_time": "18:00",
                },
            )
            self.assertEqual(weekly_open.status_code, 200, weekly_open.text)
            exception_date = target_date + timedelta(days=2)
            exception = client.post(
                "/api/v1/resources/operating-hours/exceptions",
                headers=self.admin_headers,
                json={
                    "resource_ids": [resource_id],
                    "start_date": exception_date.isoformat(),
                    "end_date": exception_date.isoformat(),
                    "is_closed": True,
                    "reason": f"{marker} campus holiday",
                },
            )
            self.assertEqual(exception.status_code, 201, exception.text)
            exception_ids.extend(exception.json()["exception_ids"])
            exception_booking = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_id,
                    "start_time": f"{exception_date.isoformat()}T09:00:00",
                    "end_time": f"{exception_date.isoformat()}T10:00:00",
                    "purpose": f"{marker} exception date",
                },
            )
            self.assertEqual(exception_booking.status_code, 409, exception_booking.text)
            self.assertIn(f"{marker} campus holiday", exception_booking.json()["detail"])

            overnight = client.put(
                "/api/v1/resources/operating-hours/bulk",
                headers=self.admin_headers,
                json={
                    "resource_ids": [resource_id],
                    "weekdays": all_days,
                    "closed_days": [],
                    "open_time": "20:00",
                    "close_time": "02:00",
                },
            )
            self.assertEqual(overnight.status_code, 200, overnight.text)
            overnight_date = target_date + timedelta(days=4)
            overnight_booking = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_id,
                    "start_time": f"{overnight_date.isoformat()}T00:30:00",
                    "end_time": f"{overnight_date.isoformat()}T01:30:00",
                    "purpose": f"{marker} overnight opening",
                },
            )
            self.assertEqual(overnight_booking.status_code, 201, overnight_booking.text)
            booking_ids.append(overnight_booking.json()["booking_id"])

            daytime = client.put(
                "/api/v1/resources/operating-hours/bulk",
                headers=self.admin_headers,
                json={
                    "resource_ids": [resource_id],
                    "weekdays": all_days,
                    "closed_days": [],
                    "open_time": "08:00",
                    "close_time": "18:00",
                },
            )
            self.assertEqual(daytime.status_code, 200, daytime.text)
            race_date = target_date + timedelta(days=6)
            race_start = datetime.combine(race_date, datetime.min.time()).replace(hour=10)
            barrier = threading.Barrier(2)

            def simultaneous_request(headers, purpose):
                barrier.wait(timeout=10)
                return client.post(
                    "/api/v1/bookings",
                    headers=headers,
                    json={
                        "resource_id": resource_id,
                        "start_time": race_start.isoformat(),
                        "end_time": (race_start + timedelta(hours=1)).isoformat(),
                        "purpose": f"{marker} {purpose}",
                    },
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(simultaneous_request, self.student_headers, "race user A"),
                    executor.submit(simultaneous_request, second_headers, "race user B"),
                ]
                responses = [future.result(timeout=30) for future in futures]
            self.assertEqual(sorted(response.status_code for response in responses), [201, 409])
            booking_ids.extend(response.json()["booking_id"] for response in responses if response.status_code == 201)

            deactivated = client.put(
                "/api/v1/resources/operating-hours/bulk",
                headers=self.admin_headers,
                json={
                    "resource_ids": [resource_id],
                    "weekdays": all_days,
                    "closed_days": [],
                    "open_time": "08:00",
                    "close_time": "18:00",
                    "is_active": False,
                },
            )
            self.assertEqual(deactivated.status_code, 200, deactivated.text)
            listed_schedule = client.get(
                "/api/v1/resources/operating-hours",
                headers=self.admin_headers,
                params={"resource_id": resource_id},
            )
            self.assertEqual(listed_schedule.status_code, 200, listed_schedule.text)
            self.assertTrue(listed_schedule.json())
            self.assertTrue(all(not row["is_active"] for row in listed_schedule.json()))
            after_deactivation = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_id,
                    "start_time": f"{race_date.isoformat()}T19:00:00",
                    "end_time": f"{race_date.isoformat()}T20:00:00",
                    "purpose": f"{marker} inactive schedule allows evening",
                },
            )
            self.assertEqual(after_deactivation.status_code, 201, after_deactivation.text)
            booking_ids.append(after_deactivation.json()["booking_id"])
        finally:
            conn = pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT booking_id FROM booking_resources WHERE resource_id = %s", (resource_id,))
            all_booking_ids = [row[0] for row in cursor.fetchall()]
            for booking_id in all_booking_ids:
                cursor.execute("DELETE FROM notifications WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_participants WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_equipment_items WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_approvals WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_audit WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM booking_resources WHERE booking_id = %s", (booking_id,))
                cursor.execute("DELETE FROM bookings WHERE booking_id = %s", (booking_id,))
            cursor.execute(
                "DELETE FROM system_audit WHERE entity_type = 'ResourceOperatingHours' AND entity_id = %s",
                (resource_id,),
            )
            cursor.execute(
                "DELETE FROM system_audit WHERE entity_type = 'ResourceOperatingHoursException' AND entity_id IN "
                "(SELECT exception_id FROM resource_operating_hour_exceptions WHERE resource_id = %s)",
                (resource_id,),
            )
            cursor.execute("DELETE FROM resource_operating_hour_exceptions WHERE resource_id = %s", (resource_id,))
            cursor.execute("DELETE FROM resource_operating_hours WHERE resource_id = %s", (resource_id,))
            cursor.execute("DELETE FROM resource_features WHERE resource_id = %s", (resource_id,))
            cursor.execute("DELETE FROM resources WHERE resource_id = %s", (resource_id,))
            if second_user_id:
                cursor.execute("DELETE FROM notifications WHERE user_id = %s", (second_user_id,))
                cursor.execute("DELETE FROM users WHERE user_id = %s", (second_user_id,))
            conn.commit()
            cursor.close()
            conn.close()

    def test_maintenance_conflict_preview_confirmation_and_notification(self):
        """Maintenance conflicts require explicit review and leave existing booking history intact."""
        marker = f"maint-conflict-{int(datetime.now().timestamp() * 1000)}"
        category = client.get("/api/v1/categories")
        self.assertEqual(category.status_code, 200, category.text)
        resource_response = client.post(
            "/api/v1/resources",
            headers=self.admin_headers,
            json={
                "category_id": category.json()[0]["category_id"],
                "resource_name": f"{marker} Room",
                "resource_code": f"MT-{marker[-10:]}",
                "location": "Maintenance Test Block",
                "capacity": 20,
                "status": "Available",
            },
        )
        self.assertEqual(resource_response.status_code, 201, resource_response.text)
        resource_id = resource_response.json()["resource_id"]
        target = datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)).replace(tzinfo=None) + timedelta(days=8)
        start = target.replace(hour=10, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=2)
        booking = client.post(
            "/api/v1/bookings",
            headers=self.student_headers,
            json={
                "resource_id": resource_id,
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(hours=1)).isoformat(),
                "purpose": f"{marker} approved booking",
            },
        )
        self.assertEqual(booking.status_code, 201, booking.text)
        booking_id = booking.json()["booking_id"]
        maintenance_id = None
        pool = get_connection_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()

        try:
            maintenance_payload = {
                "resource_id": resource_id,
                "issue_description": f"{marker} scheduled projector inspection",
                "maintenance_type": "Inspection",
                "start_datetime": start.isoformat(),
                "end_datetime": end.isoformat(),
            }
            preview = client.post(
                "/api/v1/maintenance",
                headers=self.admin_headers,
                json=maintenance_payload,
            )
            self.assertEqual(preview.status_code, 409, preview.text)
            self.assertTrue(preview.json()["detail"]["requires_confirmation"])
            self.assertEqual(preview.json()["detail"]["conflict_count"], 1)
            self.assertEqual(preview.json()["detail"]["conflicts"][0]["booking_id"], booking_id)
            booking_after_preview = client.get(f"/api/v1/bookings/{booking_id}", headers=self.student_headers)
            self.assertEqual(booking_after_preview.status_code, 200, booking_after_preview.text)
            self.assertEqual(booking_after_preview.json()["status"], booking.json()["status"])

            confirmed = client.post(
                "/api/v1/maintenance",
                headers=self.admin_headers,
                json={**maintenance_payload, "confirm_booking_conflicts": True},
            )
            self.assertEqual(confirmed.status_code, 201, confirmed.text)
            maintenance_id = confirmed.json()["maintenance_id"]
            self.assertEqual(confirmed.json()["maintenance_type"], "Inspection")
            self.assertEqual(confirmed.json()["status"], "Open")
            booking_after_confirmation = client.get(
                f"/api/v1/bookings/{booking_id}",
                headers=self.student_headers,
            )
            self.assertEqual(booking_after_confirmation.status_code, 200, booking_after_confirmation.text)
            self.assertEqual(booking_after_confirmation.json()["status"], booking.json()["status"])
            resource_after_scheduling = client.get(f"/api/v1/resources/{resource_id}")
            self.assertEqual(resource_after_scheduling.status_code, 200, resource_after_scheduling.text)
            self.assertEqual(resource_after_scheduling.json()["status"], "Available")

            conflicted_booking = client.post(
                "/api/v1/bookings",
                headers=self.student_headers,
                json={
                    "resource_id": resource_id,
                    "start_time": (start + timedelta(minutes=15)).isoformat(),
                    "end_time": (start + timedelta(minutes=45)).isoformat(),
                    "purpose": f"{marker} blocked by inspection",
                },
            )
            self.assertEqual(conflicted_booking.status_code, 409, conflicted_booking.text)
            self.assertIn(f"{marker} scheduled projector inspection", conflicted_booking.json()["detail"])
            self.assertIn("Reason category: Maintenance", conflicted_booking.json()["detail"])

            student_notifications = client.get(
                "/api/v1/notifications",
                headers=self.student_headers,
                params={"is_read": False},
            )
            self.assertEqual(student_notifications.status_code, 200, student_notifications.text)
            self.assertTrue(any(
                notification["booking_id"] == booking_id and "Maintenance (Inspection)" in notification["message"]
                for notification in student_notifications.json()
            ))
        finally:
            conn = pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM notifications WHERE booking_id = %s", (booking_id,))
            cursor.execute("DELETE FROM booking_participants WHERE booking_id = %s", (booking_id,))
            cursor.execute("DELETE FROM booking_equipment_items WHERE booking_id = %s", (booking_id,))
            cursor.execute("DELETE FROM booking_approvals WHERE booking_id = %s", (booking_id,))
            cursor.execute("DELETE FROM booking_audit WHERE booking_id = %s", (booking_id,))
            cursor.execute("DELETE FROM booking_resources WHERE booking_id = %s", (booking_id,))
            cursor.execute("DELETE FROM bookings WHERE booking_id = %s", (booking_id,))
            if maintenance_id:
                cursor.execute(
                    "DELETE FROM resource_blackout_periods WHERE maintenance_id = %s",
                    (maintenance_id,),
                )
                cursor.execute(
                    "DELETE FROM system_audit WHERE entity_type = 'Maintenance' AND entity_id = %s",
                    (maintenance_id,),
                )
                cursor.execute("DELETE FROM maintenance_records WHERE maintenance_id = %s", (maintenance_id,))
            cursor.execute("DELETE FROM resource_features WHERE resource_id = %s", (resource_id,))
            cursor.execute("DELETE FROM resources WHERE resource_id = %s", (resource_id,))
            conn.commit()
            cursor.close()
            conn.close()


if __name__ == "__main__":
    unittest.main()
