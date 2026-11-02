from datetime import datetime
from typing import Dict, Any, List, Optional


def calculate_equipment_availability(
    cursor,
    item_id: int,
    start_dt: datetime,
    end_dt: datetime,
    exclude_booking_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Centrally calculates dynamic equipment stock availability for a given time window.
    Formula:
        Available = Total - Damaged - Maintenance - Lost - Reserved (overlapping) - Overdue (outstanding unreturned)
    """
    cursor.execute(
        """
        SELECT item_id, item_code, item_name, category, description, unit,
               total_quantity, damaged_quantity, maintenance_quantity, lost_quantity,
               location, is_active, availability_status, condition_status
        FROM equipment_items
        WHERE item_id = %s
        """,
        (item_id,)
    )
    eq = cursor.fetchone()
    if not eq:
        return None

    if not eq["is_active"]:
        return {
            "item_id": eq["item_id"],
            "item_code": eq["item_code"],
            "item_name": eq["item_name"],
            "category": eq["category"],
            "unit": eq["unit"],
            "total_quantity": eq["total_quantity"],
            "damaged_quantity": eq["damaged_quantity"],
            "maintenance_quantity": eq["maintenance_quantity"],
            "lost_quantity": eq["lost_quantity"],
            "usable_quantity": 0,
            "reserved_quantity": 0,
            "overdue_issued_quantity": 0,
            "available_quantity": 0,
            "availability_status": eq.get("availability_status") or "Available",
            "condition_status": eq.get("condition_status") or ("Damaged" if eq["damaged_quantity"] > 0 else "Good"),
            "is_active": False,
            "location": eq["location"]
        }

    usable_quantity = max(
        0,
        eq["total_quantity"] - eq["damaged_quantity"] - eq["maintenance_quantity"] - eq["lost_quantity"]
    )

    # Query active/pending bookings involving this equipment item
    cursor.execute(
        """
        SELECT bei.booking_id, b.status,
               COALESCE(MIN(br.start_time), b.start_time) AS slot_start,
               COALESCE(MAX(br.end_time), b.end_time) AS slot_end,
               bei.requested_quantity, bei.approved_quantity, bei.issued_quantity,
               bei.returned_good_quantity, bei.returned_damaged_quantity, bei.lost_quantity
        FROM booking_equipment_items bei
        JOIN bookings b ON bei.booking_id = b.booking_id
        LEFT JOIN booking_resources br ON b.booking_id = br.booking_id
        WHERE bei.item_id = %s
          AND b.status IN ('Pending', 'Approved')
          AND (%s IS NULL OR b.booking_id != %s)
        GROUP BY bei.booking_equipment_id, bei.booking_id, b.status, b.start_time, b.end_time,
                 bei.requested_quantity, bei.approved_quantity, bei.issued_quantity,
                 bei.returned_good_quantity, bei.returned_damaged_quantity, bei.lost_quantity
        """,
        (item_id, exclude_booking_id, exclude_booking_id)
    )
    rows = cursor.fetchall()

    reserved_in_window = 0
    overdue_issued = 0

    now = datetime.now()

    for r in rows:
        b_start = r["slot_start"]
        b_end = r["slot_end"]

        # 1. Overlapping window reservation
        is_overlapping = False
        if b_start and b_end:
            if b_start < end_dt and b_end > start_dt:
                is_overlapping = True

        if is_overlapping:
            # If approved, use approved_quantity (if > 0) else requested_quantity
            qty = r["approved_quantity"] if (r["status"] == "Approved" and r["approved_quantity"] > 0) else r["requested_quantity"]
            reserved_in_window += qty
        else:
            # 2. Outstanding unreturned issued items from past/other bookings
            # If the item was physically issued and scheduled end is in the past, but not fully returned
            returned_total = (r["returned_good_quantity"] or 0) + (r["returned_damaged_quantity"] or 0) + (r["lost_quantity"] or 0)
            issued_qty = r["issued_quantity"] or 0
            outstanding = max(0, issued_qty - returned_total)
            if outstanding > 0 and b_end and b_end <= now:
                overdue_issued += outstanding

    available_quantity = max(0, usable_quantity - reserved_in_window - overdue_issued)
    explicit_status = (eq.get("availability_status") or "Available").strip()
    if explicit_status == "Issued":
        availability_status = "Issued"
    elif explicit_status == "Maintenance" or eq["damaged_quantity"] > 0 or eq["maintenance_quantity"] > 0:
        availability_status = "Maintenance"
    else:
        availability_status = "Available"

    return {
        "item_id": eq["item_id"],
        "item_code": eq["item_code"],
        "item_name": eq["item_name"],
        "category": eq["category"],
        "unit": eq["unit"],
        "total_quantity": eq["total_quantity"],
        "damaged_quantity": eq["damaged_quantity"],
        "maintenance_quantity": eq["maintenance_quantity"],
        "lost_quantity": eq["lost_quantity"],
        "usable_quantity": usable_quantity,
        "reserved_quantity": reserved_in_window,
        "overdue_issued_quantity": overdue_issued,
        "available_quantity": available_quantity,
        "availability_status": availability_status,
        "condition_status": eq.get("condition_status") or ("Damaged" if eq["damaged_quantity"] > 0 else "Good"),
        "is_active": bool(eq["is_active"]),
        "location": eq["location"]
    }


def get_all_equipment_with_availability(
    cursor,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    category: Optional[str] = None,
    location: Optional[str] = None,
    is_active: Optional[bool] = None,
    q: Optional[str] = None,
    exclude_booking_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Lists equipment items with real-time calculated availability.
    If start_dt and end_dt are provided, calculates availability for that specific window.
    Otherwise defaults to current time window (now to now + 2 hours).
    """
    query = """
        SELECT item_id, item_code, item_name, category, description, unit,
               total_quantity, damaged_quantity, maintenance_quantity, lost_quantity,
               location, purchase_date, is_active, availability_status, condition_status,
               created_at, updated_at
        FROM equipment_items
        WHERE 1=1
    """
    params = []
    if category and category != "All":
        query += " AND category = %s"
        params.append(category)
    if location and location != "All":
        query += " AND location = %s"
        params.append(location)
    if is_active is not None:
        query += " AND is_active = %s"
        params.append(1 if is_active else 0)
    if q:
        query += " AND (item_name LIKE %s OR item_code LIKE %s OR description LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    query += " ORDER BY category ASC, item_name ASC"
    cursor.execute(query, tuple(params))
    items = cursor.fetchall()

    eval_start = start_dt or datetime.now()
    eval_end = end_dt or (eval_start.replace(hour=(eval_start.hour + 2) % 24) if eval_start.hour < 22 else eval_start)

    results = []
    for it in items:
        avail_info = calculate_equipment_availability(
            cursor,
            item_id=it["item_id"],
            start_dt=eval_start,
            end_dt=eval_end,
            exclude_booking_id=exclude_booking_id
        )
        if avail_info:
            it["available_quantity"] = avail_info["available_quantity"]
            it["reserved_quantity"] = avail_info["reserved_quantity"]
            it["usable_quantity"] = avail_info["usable_quantity"]
            it["overdue_issued_quantity"] = avail_info["overdue_issued_quantity"]
            it["availability_status"] = avail_info["availability_status"]
            it["condition_status"] = avail_info["condition_status"]
        else:
            it["available_quantity"] = 0
            it["reserved_quantity"] = 0
            it["usable_quantity"] = 0
            it["overdue_issued_quantity"] = 0
            it["availability_status"] = it.get("availability_status") or "Available"
            it["condition_status"] = it.get("condition_status") or ("Damaged" if it.get("damaged_quantity", 0) > 0 else "Good")
        it["is_active"] = bool(it["is_active"])
        results.append(it)

    return results
