import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from fastapi import HTTPException, status
from app.services.availability import campus_datetime, campus_now_naive, check_resource_availability
from app.services.equipment_availability import calculate_equipment_availability
from app.services.audit_service import log_booking_audit
from app.services.system_settings import get_booking_settings


def create_notification(
    cursor,
    user_id: int,
    message: str,
    notif_type: str = "Info",
    booking_id: Optional[int] = None,
    audience: str = "User"
):
    cursor.execute(
        """
        INSERT INTO notifications (user_id, booking_id, message, type, audience, is_read)
        VALUES (%s, %s, %s, %s, %s, 0)
        """,
        (user_id, booking_id, message, notif_type, audience)
    )


def create_booking_transaction(
    conn,
    cursor,
    user_id: int,
    user_role: str,
    purpose: str,
    resources_list: Optional[List[Dict[str, Any]]] = None,
    expected_participants: int = 1,
    society_id: Optional[int] = None,
    participants: Optional[List[int]] = None,
    equipment_requests: Optional[List[Dict[str, Any]]] = None,
    equipment_ids: Optional[List[int]] = None,
    booking_start_time: Optional[datetime] = None,
    booking_end_time: Optional[datetime] = None
) -> int:
    """
    Creates a booking within an active database transaction:
    - Supports Room booking only
    - Supports Combined Room + Equipment booking
    - Supports Equipment-only booking (collection at Gym)
    - Concurrency-safe row locking (FOR UPDATE) in ascending ID order
    - Validates dynamic stock availability inside transaction
    - Records audit and notification
    """
    resources_list = resources_list or []

    # 1. Normalize and combine equipment requests
    combined_equip: Dict[int, int] = {}
    if equipment_requests:
        for req in equipment_requests:
            item_id = int(req.get("item_id", 0))
            qty = int(req.get("quantity", 1))
            if item_id <= 0:
                raise HTTPException(status_code=400, detail="Invalid equipment item ID.")
            if qty <= 0:
                raise HTTPException(status_code=400, detail="Requested equipment quantity must be a positive integer.")
            combined_equip[item_id] = combined_equip.get(item_id, 0) + qty

    # Support legacy equipment_ids list (defaults to quantity 1 each)
    if equipment_ids:
        for eq_id in equipment_ids:
            if eq_id > 0:
                combined_equip[eq_id] = combined_equip.get(eq_id, 0) + 1

    # Empty booking rejection: Must contain either room resource or equipment
    if not resources_list and not combined_equip:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking must contain at least one space resource or equipment item."
        )

    # 2. Determine and validate overall booking time window
    now = campus_now_naive()
    booking_settings = get_booking_settings(cursor)
    overall_start_dt: Optional[datetime] = None
    overall_end_dt: Optional[datetime] = None

    if resources_list:
        for item in resources_list:
            start_dt = campus_datetime(datetime.fromisoformat(item["start_time"].replace("Z", "+00:00")))
            end_dt = campus_datetime(datetime.fromisoformat(item["end_time"].replace("Z", "+00:00")))

            if start_dt.date() != end_dt.date():
                raise HTTPException(
                    status_code=400,
                    detail="Bookings spanning across midnight are not permitted. Please submit separate single-day reservations."
                )
            if end_dt <= start_dt:
                raise HTTPException(status_code=400, detail="End time must be after start time.")
            if start_dt < now:
                raise HTTPException(status_code=400, detail="Cannot book a slot in the past.")
            if start_dt > now + timedelta(days=booking_settings["booking_window_days"]):
                raise HTTPException(
                    status_code=400,
                    detail=f"Bookings may be made no more than {booking_settings['booking_window_days']} days in advance."
                )
            duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
            if not booking_settings["min_booking_minutes"] <= duration_minutes <= booking_settings["max_booking_minutes"]:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Booking duration must be between {booking_settings['min_booking_minutes']} "
                        f"and {booking_settings['max_booking_minutes']} minutes."
                    )
                )

            if overall_start_dt is None or start_dt < overall_start_dt:
                overall_start_dt = start_dt
            if overall_end_dt is None or end_dt > overall_end_dt:
                overall_end_dt = end_dt
    else:
        # Equipment-only booking time window
        if not booking_start_time or not booking_end_time:
            raise HTTPException(
                status_code=400,
                detail="Equipment-only booking must specify start_time and end_time."
            )
        if isinstance(booking_start_time, str):
            overall_start_dt = campus_datetime(datetime.fromisoformat(booking_start_time.replace("Z", "+00:00")))
        else:
            overall_start_dt = booking_start_time

        if isinstance(booking_end_time, str):
            overall_end_dt = campus_datetime(datetime.fromisoformat(booking_end_time.replace("Z", "+00:00")))
        else:
            overall_end_dt = booking_end_time

        if overall_start_dt.date() != overall_end_dt.date():
            raise HTTPException(
                status_code=400,
                detail="Bookings spanning across midnight are not permitted. Please submit separate single-day reservations."
            )
        if overall_end_dt <= overall_start_dt:
            raise HTTPException(status_code=400, detail="End time must be after start time.")
        if overall_start_dt < now:
            raise HTTPException(status_code=400, detail="Cannot book a slot in the past.")
        if overall_start_dt > now + timedelta(days=booking_settings["booking_window_days"]):
            raise HTTPException(
                status_code=400,
                detail=f"Bookings may be made no more than {booking_settings['booking_window_days']} days in advance."
            )
        duration_minutes = int((overall_end_dt - overall_start_dt).total_seconds() // 60)
        if not booking_settings["min_booking_minutes"] <= duration_minutes <= booking_settings["max_booking_minutes"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Booking duration must be between {booking_settings['min_booking_minutes']} "
                    f"and {booking_settings['max_booking_minutes']} minutes."
                )
            )

    # 3. Society authorization check
    if society_id:
        cursor.execute("SELECT club_id, club_name, is_active, status FROM societies WHERE club_id = %s", (society_id,))
        soc = cursor.fetchone()
        if not soc or not soc["is_active"] or soc.get("status") != "Approved":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Society is not active or has not been approved by an administrator."
            )

        if user_role != "Admin":
            cursor.execute(
                """
                SELECT can_book, is_active FROM society_members
                WHERE club_id = %s AND user_id = %s
                """,
                (society_id, user_id)
            )
            membership = cursor.fetchone()
            if not membership or not membership["is_active"] or not membership["can_book"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to book spaces on behalf of this society. Requires active membership with booking permission."
                )

    # 4. Acquire row-level locks (FOR UPDATE) in ascending order to prevent deadlocks & race conditions
    # A. Resource locks
    if resources_list:
        sorted_res_ids = sorted([item["resource_id"] for item in resources_list])
        for r_id in sorted_res_ids:
            cursor.execute("SELECT resource_id, status FROM resources WHERE resource_id = %s FOR UPDATE", (r_id,))
            res_row = cursor.fetchone()
            if not res_row or res_row["status"] != "Available":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Resource ID {r_id} is not currently available for booking."
                )

    # B. Equipment locks
    if combined_equip:
        sorted_item_ids = sorted(combined_equip.keys())
        for eq_id in sorted_item_ids:
            cursor.execute(
                """
                SELECT item_id, item_name, total_quantity, damaged_quantity,
                       maintenance_quantity, lost_quantity, is_active
                FROM equipment_items
                WHERE item_id = %s
                FOR UPDATE
                """,
                (eq_id,)
            )
            eq_row = cursor.fetchone()
            if not eq_row:
                raise HTTPException(status_code=400, detail=f"Equipment item ID {eq_id} does not exist.")
            if not eq_row["is_active"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Equipment item '{eq_row['item_name']}' is currently inactive or decommissioned."
                )

    # 5. Re-verify resource availability
    for item in resources_list:
        res_id = item["resource_id"]
        start_dt = campus_datetime(datetime.fromisoformat(item["start_time"].replace("Z", "+00:00")))
        end_dt = campus_datetime(datetime.fromisoformat(item["end_time"].replace("Z", "+00:00")))

        avail = check_resource_availability(
            cursor, res_id, start_dt, end_dt, booking_settings=booking_settings, locking_read=True
        )
        if not avail["is_available"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Resource conflict for ID {res_id}: {avail['reason']}"
            )

    # 6. Re-verify equipment availability inside locked transaction
    for eq_id, req_qty in combined_equip.items():
        avail_info = calculate_equipment_availability(
            cursor,
            item_id=eq_id,
            start_dt=overall_start_dt,
            end_dt=overall_end_dt,
            locking_read=True
        )
        if not avail_info or not avail_info["is_active"]:
            raise HTTPException(
                status_code=400,
                detail=f"Equipment item ID {eq_id} is inactive or not found."
            )
        if avail_info.get("blackout"):
            blackout = avail_info["blackout"]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Equipment unavailable due to {blackout['reason_category']}: "
                    f"{blackout['reason_explanation']} "
                    f"({avail_info['item_name']} blocked from {blackout['start_datetime']:%Y-%m-%d %H:%M} "
                    f"to {blackout['end_datetime']:%Y-%m-%d %H:%M})"
                ),
            )
        if req_qty > avail_info["available_quantity"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Insufficient stock for '{avail_info['item_name']}'. "
                    f"Requested: {req_qty}, Currently Available: {avail_info['available_quantity']} "
                    f"(Total: {avail_info['total_quantity']}, Reserved: {avail_info['reserved_quantity']})."
                )
            )

    # 7. Apply the configured approval policy; manual approval remains the default.
    initial_status = "Pending"
    if booking_settings["approval_mode"] == "ByCategory":
        requested_categories = set()
        if resources_list:
            cursor.execute(
                f"""
                SELECT DISTINCT c.category_name
                FROM resources r JOIN categories c ON r.category_id = c.category_id
                WHERE r.resource_id IN ({','.join(['%s'] * len(resources_list))})
                """,
                tuple(item["resource_id"] for item in resources_list)
            )
            requested_categories.update(row["category_name"] for row in cursor.fetchall())
        if combined_equip:
            cursor.execute(
                f"SELECT DISTINCT category FROM equipment_items WHERE item_id IN ({','.join(['%s'] * len(combined_equip))})",
                tuple(combined_equip)
            )
            requested_categories.update(row["category"] for row in cursor.fetchall() if row["category"])
        if not requested_categories.intersection(booking_settings["approval_categories"]):
            initial_status = "Approved"

    # 8. Insert into bookings
    cursor.execute(
        """
        INSERT INTO bookings (user_id, society_id, purpose, expected_participants, status, start_time, end_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, society_id, purpose, expected_participants, initial_status, overall_start_dt, overall_end_dt)
    )
    booking_id = cursor.lastrowid

    # 9. Insert into booking_resources
    for item in resources_list:
        res_id = item["resource_id"]
        start_dt = campus_datetime(datetime.fromisoformat(item["start_time"].replace("Z", "+00:00")))
        end_dt = campus_datetime(datetime.fromisoformat(item["end_time"].replace("Z", "+00:00")))

        cursor.execute(
            """
            INSERT INTO booking_resources (booking_id, resource_id, start_time, end_time, status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (booking_id, res_id, start_dt, end_dt, initial_status)
        )

    # 10. Insert participants
    cursor.execute(
        """
        INSERT INTO booking_participants (booking_id, user_id, participant_role, attendance_status)
        VALUES (%s, %s, 'Organizer', 'Attending')
        """,
        (booking_id, user_id)
    )

    if participants:
        for p_id in set(participants):
            if p_id != user_id:
                cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (p_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=400, detail=f"Participant user ID {p_id} does not exist.")
                cursor.execute(
                    """
                    INSERT INTO booking_participants (booking_id, user_id, participant_role, attendance_status)
                    VALUES (%s, %s, 'Participant', 'Invited')
                    """,
                    (booking_id, p_id)
                )

    # 11. Reserve equipment items with quantities (issued_quantity starts at 0 until physical handover)
    if combined_equip:
        for eq_id, req_qty in combined_equip.items():
            approved_qty = req_qty if initial_status == "Approved" else 0
            cursor.execute(
                """
                INSERT INTO booking_equipment_items (
                    booking_id, item_id, requested_quantity, approved_quantity,
                    issued_quantity, returned_good_quantity, returned_damaged_quantity, lost_quantity
                )
                VALUES (%s, %s, %s, %s, 0, 0, 0, 0)
                """,
                (booking_id, eq_id, req_qty, approved_qty)
            )

    # 12. Audit log & Notification
    new_state = {
        "status": initial_status,
        "purpose": purpose,
        "resources_count": len(resources_list),
        "equipment_items_count": len(combined_equip),
        "society_id": society_id
    }
    log_booking_audit(
        cursor,
        booking_id=booking_id,
        changed_by=user_id,
        action="Created",
        old_values=None,
        new_values=new_state,
        remarks=f"Booking created with initial status {initial_status}."
    )

    # Fetch requester name for informative notifications
    cursor.execute("SELECT name, email FROM users WHERE user_id = %s", (user_id,))
    requester_info = cursor.fetchone()
    requester_label = requester_info["name"] if (requester_info and requester_info.get("name")) else f"User #{user_id}"
    cursor.execute(
        """
        SELECT
            (SELECT GROUP_CONCAT(DISTINCT r.resource_name ORDER BY r.resource_name SEPARATOR ', ')
             FROM booking_resources br JOIN resources r ON r.resource_id = br.resource_id
             WHERE br.booking_id = %s) AS resource_names,
            (SELECT GROUP_CONCAT(DISTINCT ei.item_name ORDER BY ei.item_name SEPARATOR ', ')
             FROM booking_equipment_items bei JOIN equipment_items ei ON ei.item_id = bei.item_id
             WHERE bei.booking_id = %s) AS equipment_names
        """,
        (booking_id, booking_id)
    )
    booking_items = cursor.fetchone()
    item_context = ", ".join(
        value for value in (
            booking_items.get("resource_names"),
            booking_items.get("equipment_names")
        ) if value
    ) or "campus resources"

    # Notification for the requester
    create_notification(
        cursor,
        user_id=user_id,
        message=(
            f"Your booking BK-{booking_id} for '{purpose}' has been approved automatically."
            if initial_status == "Approved"
            else f"Your booking request BK-{booking_id} for '{purpose}' has been submitted and is pending Administrator approval."
        ),
        notif_type="Approval" if initial_status == "Approved" else "Info",
        booking_id=booking_id
    )

    if initial_status == "Pending":
        cursor.execute("SELECT user_id FROM users WHERE role = 'Admin' AND is_active = 1")
        admins = cursor.fetchall()
        for adm in admins:
            if adm["user_id"] != user_id:
                create_notification(
                    cursor,
                    user_id=adm["user_id"],
                    message=f"New booking request BK-{booking_id} for '{purpose}' ({item_context}) submitted by {requester_label} requires your approval.",
                    notif_type="Alert",
                    booking_id=booking_id,
                    audience="Admin"
                )

    return booking_id
