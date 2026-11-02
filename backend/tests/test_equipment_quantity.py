"""
Comprehensive Test Suite for Quantity-Based Sports and Electronic Equipment Module
Database: smart_campus_test
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# Set test environment
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

os.environ["DB_NAME"] = "smart_campus_test"
from app.core.config import settings
settings.DB_NAME = "smart_campus_test"

import app.database.connection as db_conn
db_conn._pool = None  # reset pool

from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token
from tests.setup_test_db import setup_isolated_test_database


class TestEquipmentQuantitySystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_isolated_test_database()
        cls.client = TestClient(app)

        cls.admin_token = create_access_token(
            subject=1,
            extra_claims={"email": "admin.test@campus.edu", "role": "Admin", "name": "Admin Tester"}
        )
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.student_token = create_access_token(
            subject=4,
            extra_claims={"email": "student.test@campus.edu", "role": "Student", "name": "Student Tester"}
        )
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}

        cls.staff_token = create_access_token(
            subject=3,
            extra_claims={"email": "staff.test@campus.edu", "role": "Staff", "name": "Staff Tester"}
        )
        cls.staff_headers = {"Authorization": f"Bearer {cls.staff_token}"}

    # ---------------------------------------------------------
    # 1. INVENTORY CRUD & VALIDATION
    # ---------------------------------------------------------
    def test_01_create_sports_and_electronics_items(self):
        # Create sports item
        res = self.client.post("/api/v1/equipment", json={
            "item_name": "Premium Badminton Racket Set",
            "item_code": "SP-BADM-99",
            "category": "Sports",
            "unit": "Set",
            "total_quantity": 25,
            "description": "Yonex carbon-frame rackets with covers"
        }, headers=self.admin_headers)
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["item_code"], "SP-BADM-99")
        self.assertEqual(data["category"], "Sports")
        self.assertEqual(data["unit"], "Set")
        self.assertEqual(data["total_quantity"], 25)
        self.assertEqual(data["available_quantity"], 25)
        self.assertEqual(data["location"], "Gym")

        # Create electronic item
        res2 = self.client.post("/api/v1/equipment", json={
            "item_name": "Ultra-HD Wireless Presentation Remote",
            "item_code": "EL-CLICK-88",
            "category": "Electronics",
            "unit": "Piece",
            "total_quantity": 15,
            "description": "Logitech presentation remotes with green laser"
        }, headers=self.admin_headers)
        self.assertEqual(res2.status_code, 201, res2.text)
        data2 = res2.json()
        self.assertEqual(data2["item_code"], "EL-CLICK-88")
        self.assertEqual(data2["category"], "Electronics")
        self.assertEqual(data2["available_quantity"], 15)

    def test_02_duplicate_item_code_rejected(self):
        res = self.client.post("/api/v1/equipment", json={
            "item_name": "Duplicate Item",
            "item_code": "SP-BADM-99",
            "category": "Sports",
            "unit": "Piece",
            "total_quantity": 5
        }, headers=self.admin_headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", res.text)

    def test_03_student_cannot_create_or_modify_inventory(self):
        res = self.client.post("/api/v1/equipment", json={
            "item_name": "Unauthorized Equipment",
            "item_code": "UNAUTH-01",
            "category": "Sports",
            "unit": "Piece",
            "total_quantity": 10
        }, headers=self.student_headers)
        self.assertEqual(res.status_code, 403)

    # ---------------------------------------------------------
    # 2. STOCK ADJUSTMENTS & MOVEMENT AUDIT
    # ---------------------------------------------------------
    def test_04_stock_adjustment_lifecycle_and_movements(self):
        # 1. Fetch item
        res = self.client.get("/api/v1/equipment", headers=self.admin_headers)
        items = res.json()
        target = next(it for it in items if it["item_code"] == "SP-BADM-99")
        item_id = target["item_id"]

        # 2. Add Stock (+5)
        res_adj = self.client.post(f"/api/v1/equipment/{item_id}/stock", json={
            "adjustment_type": "add",
            "quantity": 5,
            "notes": "Annual equipment grant purchase"
        }, headers=self.admin_headers)
        self.assertEqual(res_adj.status_code, 200)
        self.assertEqual(res_adj.json()["total_quantity"], 30)
        self.assertEqual(res_adj.json()["available_quantity"], 30)

        # 3. Report Damaged (3)
        res_adj = self.client.post(f"/api/v1/equipment/{item_id}/stock", json={
            "adjustment_type": "damage",
            "quantity": 3,
            "notes": "Strings snapped during college tournament"
        }, headers=self.admin_headers)
        self.assertEqual(res_adj.status_code, 200)
        self.assertEqual(res_adj.json()["damaged_quantity"], 3)
        self.assertEqual(res_adj.json()["available_quantity"], 27)

        # 4. Send to Maintenance (2 of the damaged items)
        res_adj = self.client.post(f"/api/v1/equipment/{item_id}/stock", json={
            "adjustment_type": "maintenance",
            "quantity": 2,
            "notes": "Sent to sports vendor for rewiring"
        }, headers=self.admin_headers)
        self.assertEqual(res_adj.status_code, 200)
        self.assertEqual(res_adj.json()["maintenance_quantity"], 2)
        self.assertEqual(res_adj.json()["damaged_quantity"], 1)
        self.assertEqual(res_adj.json()["available_quantity"], 27)

        # 5. Repair (1 returned)
        res_adj = self.client.post(f"/api/v1/equipment/{item_id}/stock", json={
            "adjustment_type": "repair",
            "quantity": 1,
            "notes": "1 racket returned repaired"
        }, headers=self.admin_headers)
        self.assertEqual(res_adj.status_code, 200)
        self.assertEqual(res_adj.json()["maintenance_quantity"], 1)
        self.assertEqual(res_adj.json()["available_quantity"], 28)

        # 6. Report Lost (1)
        res_adj = self.client.post(f"/api/v1/equipment/{item_id}/stock", json={
            "adjustment_type": "lost",
            "quantity": 1,
            "notes": "Lost during practice session"
        }, headers=self.admin_headers)
        self.assertEqual(res_adj.status_code, 200)
        self.assertEqual(res_adj.json()["lost_quantity"], 1)
        self.assertEqual(res_adj.json()["available_quantity"], 27)

        # 7. Check stock movements audit log
        res_mov = self.client.get(f"/api/v1/equipment/{item_id}/movements", headers=self.admin_headers)
        self.assertEqual(res_mov.status_code, 200)
        movements = res_mov.json()
        self.assertGreaterEqual(len(movements), 5)
        types = [m["movement_type"] for m in movements]
        self.assertIn("Stock Added", types)
        self.assertIn("Returned Damaged", types)
        self.assertIn("Moved to Maintenance", types)
        self.assertIn("Repaired", types)
        self.assertIn("Lost", types)

    # ---------------------------------------------------------
    # 3. BOOKINGS WITH QUANTITIES & EQUIPMENT-ONLY
    # ---------------------------------------------------------
    def test_05_equipment_only_booking_with_quantity(self):
        res = self.client.get("/api/v1/equipment", headers=self.admin_headers)
        badminton = next(it for it in res.json() if it["item_code"] == "SP-BADM-99")
        remote = next(it for it in res.json() if it["item_code"] == "EL-CLICK-88")

        start = (datetime.now() + timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=2)

        # Submit equipment-only booking
        res_book = self.client.post("/api/v1/bookings", json={
            "purpose": "Inter-department badminton trials and presentation session",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "equipment_requests": [
                {"item_id": badminton["item_id"], "quantity": 10},
                {"item_id": remote["item_id"], "quantity": 2}
            ],
            "expected_participants": 20
        }, headers=self.student_headers)
        self.assertEqual(res_book.status_code, 201, res_book.text)
        b_data = res_book.json()
        self.assertEqual(len(b_data["equipment"]), 2)
        eq1 = next(e for e in b_data["equipment"] if e["item_id"] == badminton["item_id"])
        self.assertEqual(eq1["requested_quantity"], 10)
        self.assertEqual(eq1["location"], "Gym")

    def test_06_dynamic_overlapping_stock_deduction(self):
        res = self.client.get("/api/v1/equipment", headers=self.admin_headers)
        badminton = next(it for it in res.json() if it["item_code"] == "SP-BADM-99")

        start = (datetime.now() + timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=2)

        # Dynamic availability during overlapping slot should reflect -10 units
        res_avail = self.client.get(
            f"/api/v1/equipment/{badminton['item_id']}/availability",
            params={"start_time": start.isoformat(), "end_time": end.isoformat()},
            headers=self.student_headers
        )
        self.assertEqual(res_avail.status_code, 200)
        avail_data = res_avail.json()
        self.assertEqual(avail_data["reserved_quantity"], 10)
        self.assertEqual(avail_data["available_quantity"], 17)  # 27 usable - 10 reserved = 17

        # Non-overlapping slot on day 3 should still have full 27 available
        other_start = (datetime.now() + timedelta(days=3)).replace(hour=14, minute=0, second=0, microsecond=0)
        other_end = other_start + timedelta(hours=2)
        res_avail2 = self.client.get(
            f"/api/v1/equipment/{badminton['item_id']}/availability",
            params={"start_time": other_start.isoformat(), "end_time": other_end.isoformat()},
            headers=self.student_headers
        )
        self.assertEqual(res_avail2.status_code, 200)
        self.assertEqual(res_avail2.json()["reserved_quantity"], 0)
        self.assertEqual(res_avail2.json()["available_quantity"], 27)

    def test_07_insufficient_stock_overbooking_rejected(self):
        res = self.client.get("/api/v1/equipment", headers=self.admin_headers)
        badminton = next(it for it in res.json() if it["item_code"] == "SP-BADM-99")

        start = (datetime.now() + timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=2)

        # Only 17 available in this overlapping slot; attempting to request 20 must fail
        res_over = self.client.post("/api/v1/bookings", json={
            "purpose": "Excessive request exceeding available stock",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "equipment_requests": [
                {"item_id": badminton["item_id"], "quantity": 20}
            ],
            "expected_participants": 20
        }, headers=self.student_headers)
        self.assertEqual(res_over.status_code, 409)
        self.assertIn("Insufficient stock", res_over.text)

    # ---------------------------------------------------------
    # 4. ISSUE & RETURN WORKFLOW AT CAMPUS GYM
    # ---------------------------------------------------------
    def test_08_issue_and_return_workflow(self):
        res = self.client.get("/api/v1/equipment", headers=self.admin_headers)
        remote = next(it for it in res.json() if it["item_code"] == "EL-CLICK-88")

        start = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=2)

        # 1. Create and approve booking
        res_book = self.client.post("/api/v1/bookings", json={
            "purpose": "Seminar with wireless presenter clickers",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "equipment_requests": [
                {"item_id": remote["item_id"], "quantity": 5}
            ],
            "expected_participants": 30
        }, headers=self.student_headers)
        self.assertEqual(res_book.status_code, 201)
        booking_data = res_book.json()
        booking_id = booking_data["booking_id"]

        if booking_data["status"] == "Pending":
            res_appr = self.client.post(f"/api/v1/approvals/{booking_id}/approve", json={
                "action": "Approve",
                "remarks": "Approved with presentation clickers"
            }, headers=self.admin_headers)
            self.assertEqual(res_appr.status_code, 200)

        # 2. Staff issues equipment at Gym desk (5 units)
        res_issue = self.client.post(f"/api/v1/equipment/{remote['item_id']}/issue", json={
            "booking_id": booking_id,
            "quantity": 5,
            "notes": "Issued at campus Gym collection counter"
        }, headers=self.staff_headers)
        self.assertEqual(res_issue.status_code, 200)
        self.assertEqual(res_issue.json()["total_issued"], 5)

        # 3. Reject excess return (attempting to return 6 when 5 issued)
        res_ret_bad = self.client.post(f"/api/v1/equipment/{remote['item_id']}/return", json={
            "booking_id": booking_id,
            "good_quantity": 6,
            "damaged_quantity": 0,
            "lost_quantity": 0,
            "notes": "Excess return attempt"
        }, headers=self.staff_headers)
        self.assertEqual(res_ret_bad.status_code, 400)
        self.assertIn("Cannot return", res_ret_bad.text)

        # 4. Return equipment: 3 good, 1 damaged, 1 lost
        res_ret = self.client.post(f"/api/v1/equipment/{remote['item_id']}/return", json={
            "booking_id": booking_id,
            "good_quantity": 3,
            "damaged_quantity": 1,
            "lost_quantity": 1,
            "notes": "Returned at Gym desk: 1 battery cover cracked, 1 lost"
        }, headers=self.staff_headers)
        self.assertEqual(res_ret.status_code, 200)
        ret_data = res_ret.json()
        self.assertEqual(ret_data["returned_good_quantity"], 3)
        self.assertEqual(ret_data["returned_damaged_quantity"], 1)
        self.assertEqual(ret_data["lost_quantity"], 1)

        # 5. Check item stock counts updated
        res_item = self.client.get(f"/api/v1/equipment/{remote['item_id']}", headers=self.admin_headers)
        item_data = res_item.json()
        self.assertEqual(item_data["damaged_quantity"], 1)
        self.assertEqual(item_data["lost_quantity"], 1)

    # ---------------------------------------------------------
    # 5. CONCURRENT BOOKING SAFETY (RACE CONDITION)
    # ---------------------------------------------------------
    def test_09_concurrency_race_condition_protection(self):
        # Create an item with exact quantity 2
        res = self.client.post("/api/v1/equipment", json={
            "item_name": "Exclusive Tournament Trophy Ball",
            "item_code": "SP-BALL-RACE",
            "category": "Sports",
            "unit": "Piece",
            "total_quantity": 2,
            "description": "High value limited equipment"
        }, headers=self.admin_headers)
        self.assertEqual(res.status_code, 201)
        item_id = res.json()["item_id"]

        start = (datetime.now() + timedelta(days=4)).replace(hour=16, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=2)

        # Launch two simultaneous booking requests each demanding 2 units for the same slot
        def make_booking(user_token):
            c = TestClient(app)
            return c.post("/api/v1/bookings", json={
                "purpose": "Race condition test booking",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "equipment_requests": [{"item_id": item_id, "quantity": 2}],
                "expected_participants": 5
            }, headers={"Authorization": f"Bearer {user_token}"})

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(make_booking, self.student_token)
            fut2 = executor.submit(make_booking, self.student_token)
            r1 = fut1.result()
            r2 = fut2.result()

        statuses = [r1.status_code, r2.status_code]
        # Exactly one must succeed (201) and the other must be rejected (409 Conflict)
        self.assertIn(201, statuses, "One booking must succeed")
        self.assertIn(409, statuses, "One booking must fail due to exhausted stock")


if __name__ == "__main__":
    unittest.main()
