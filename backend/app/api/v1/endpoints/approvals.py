from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.booking import BookingResponse
from app.schemas.approval import ApprovalAction, ApprovalResponse
from app.api.v1.endpoints.bookings import format_booking_row
from app.services.availability import check_resource_availability
from app.services.booking_workflow import create_notification
from app.services.audit_service import log_booking_audit

router = APIRouter()


@router.get("/pending", response_model=List[BookingResponse], summary="List pending booking requests for approval (Admin)")
def get_pending_approvals(current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    db.execute(
        """
        SELECT b.booking_id, b.user_id, b.society_id, b.purpose, b.expected_participants,
               b.status, b.start_time, b.end_time, b.created_at, b.updated_at,
               u.name as user_name, u.email as user_email,
               s.club_name
        FROM bookings b
        JOIN users u ON b.user_id = u.user_id
        LEFT JOIN societies s ON b.society_id = s.club_id
        WHERE b.status = 'Pending'
        ORDER BY b.created_at ASC
        """
    )
    bookings = db.fetchall()
    if not bookings:
        return []

    b_ids = [b["booking_id"] for b in bookings]
    format_strings = ','.join(['%s'] * len(b_ids))
    db.execute(
        f"""
        SELECT br.booking_resource_id, br.booking_id, br.resource_id, br.start_time, br.end_time, br.status,
               r.resource_name, r.resource_code, r.location
        FROM booking_resources br
        JOIN resources r ON br.resource_id = r.resource_id
        WHERE br.booking_id IN ({format_strings})
        """,
        tuple(b_ids)
    )
    res_rows = db.fetchall()
    res_map = {}
    for r in res_rows:
        res_map.setdefault(r["booking_id"], []).append(r)

    db.execute(
        f"""
        SELECT be.booking_equipment_id, be.booking_id, be.item_id,
               be.requested_quantity, be.approved_quantity, be.issued_quantity,
               be.returned_good_quantity, be.returned_damaged_quantity, be.lost_quantity,
               eq.item_name, eq.item_code, eq.category, eq.unit, eq.location
        FROM booking_equipment_items be
        JOIN equipment_items eq ON be.item_id = eq.item_id
        WHERE be.booking_id IN ({format_strings})
        """,
        tuple(b_ids)
    )
    eq_rows = db.fetchall()
    eq_map = {}
    for e in eq_rows:
        eq_map.setdefault(e["booking_id"], []).append(e)

    return [format_booking_row(b, res_map, eq_map) for b in bookings]


@router.post("/{booking_id}/approve", summary="Approve a pending booking (Admin)")
def approve_booking(
    booking_id: int,
    action: ApprovalAction,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT booking_id, user_id, purpose, status FROM bookings WHERE booking_id = %s", (booking_id,))
    b = db.fetchone()
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    if b["status"] != "Pending":
        raise HTTPException(status_code=400, detail=f"Booking is not pending (current status: {b['status']}).")

    with transaction_scope() as (conn, cursor):
        # 1. Fetch requested resources and re-verify availability
        cursor.execute("SELECT booking_resource_id, resource_id, start_time, end_time FROM booking_resources WHERE booking_id = %s", (booking_id,))
        resources = cursor.fetchall()

        for r in resources:
            avail = check_resource_availability(
                cursor,
                r["resource_id"],
                r["start_time"],
                r["end_time"],
                exclude_booking_id=booking_id
            )
            if not avail["is_available"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Resource ID {r['resource_id']} is no longer available: {avail['reason']}"
                )

        # 2. Update booking and booking_resources status to 'Approved'
        cursor.execute("UPDATE bookings SET status = 'Approved' WHERE booking_id = %s", (booking_id,))
        cursor.execute("UPDATE booking_resources SET status = 'Approved' WHERE booking_id = %s", (booking_id,))
        cursor.execute(
            """
            UPDATE booking_equipment_items
            SET approved_quantity = requested_quantity
            WHERE booking_id = %s
            """,
            (booking_id,)
        )

        # 3. Insert into booking_approvals
        cursor.execute(
            """
            INSERT INTO booking_approvals (booking_id, approver_id, decision, remarks, decided_at)
            VALUES (%s, %s, 'Approved', %s, %s)
            """,
            (booking_id, current_user.user_id, action.remarks or "Approved", datetime.now())
        )

        # 4. Insert audit log
        log_booking_audit(
            cursor,
            booking_id=booking_id,
            changed_by=current_user.user_id,
            action="Approved",
            old_values={"status": "Pending"},
            new_values={"status": "Approved"},
            remarks=action.remarks or "Approved by manager"
        )

        # 5. Insert notification for requester
        approval_note = f" Remarks: {action.remarks}" if action.remarks and action.remarks.strip() != "Approved" else ""
        create_notification(
            cursor,
            user_id=b["user_id"],
            message=f"Your booking BK-{booking_id} ('{b['purpose']}') has been approved by Administrator!{approval_note}",
            notif_type="Approval",
            booking_id=booking_id
        )

        # Notify participants
        cursor.execute(
            "SELECT user_id FROM booking_participants WHERE booking_id = %s AND user_id != %s",
            (booking_id, b["user_id"])
        )
        for part in cursor.fetchall():
            create_notification(
                cursor,
                user_id=part["user_id"],
                message=f"Booking BK-{booking_id} ('{b['purpose']}') has been approved by Administrator.",
                notif_type="Info",
                booking_id=booking_id
            )

    return {"message": "Booking approved successfully", "booking_id": booking_id, "status": "Approved"}


@router.post("/{booking_id}/reject", summary="Reject a pending booking (Admin)")
def reject_booking(
    booking_id: int,
    action: ApprovalAction,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    db.execute("SELECT booking_id, user_id, purpose, status FROM bookings WHERE booking_id = %s", (booking_id,))
    b = db.fetchone()
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    if b["status"] != "Pending":
        raise HTTPException(status_code=400, detail=f"Booking is not pending (current status: {b['status']}).")

    with transaction_scope() as (conn, cursor):
        # 1. Update booking and booking_resources to 'Rejected'
        cursor.execute("UPDATE bookings SET status = 'Rejected' WHERE booking_id = %s", (booking_id,))
        cursor.execute("UPDATE booking_resources SET status = 'Rejected' WHERE booking_id = %s", (booking_id,))

        # 2. Release any equipment reserved (only if not damaged and not in maintenance)
        cursor.execute("SELECT item_id FROM booking_equipment_items WHERE booking_id = %s", (booking_id,))
        for eq in cursor.fetchall():
            cursor.execute(
                """
                UPDATE equipment_items
                SET availability_status = 'Available'
                WHERE item_id = %s AND condition_status != 'Damaged' AND availability_status != 'Maintenance'
                """,
                (eq["item_id"],)
            )

        # 3. Insert into booking_approvals
        cursor.execute(
            """
            INSERT INTO booking_approvals (booking_id, approver_id, decision, remarks, decided_at)
            VALUES (%s, %s, 'Rejected', %s, %s)
            """,
            (booking_id, current_user.user_id, action.remarks or "Rejected", datetime.now())
        )

        # 4. Insert audit log
        log_booking_audit(
            cursor,
            booking_id=booking_id,
            changed_by=current_user.user_id,
            action="Rejected",
            old_values={"status": "Pending"},
            new_values={"status": "Rejected"},
            remarks=action.remarks or "Rejected by manager"
        )

        # 5. Insert notification for requester
        create_notification(
            cursor,
            user_id=b["user_id"],
            message=f"Your booking BK-{booking_id} ('{b['purpose']}') was rejected. Remarks: {action.remarks or 'None'}",
            notif_type="Alert",
            booking_id=booking_id
        )

    return {"message": "Booking rejected", "booking_id": booking_id, "status": "Rejected"}
