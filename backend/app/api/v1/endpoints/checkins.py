from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import get_current_user, require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.checkin import CheckinCreate, CheckoutRequest, NoShowRequest, CheckinResponse
from app.services.audit_service import log_system_audit

router = APIRouter()


@router.get("", response_model=List[CheckinResponse], summary="List check-ins / attendance history (Admin/Staff/Self)")
def list_checkins(
    booking_id: Optional[int] = Query(None),
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    query = """
        SELECT c.checkin_id, c.booking_participant_id, c.verified_by, c.checkin_time,
               c.checkout_time, c.status, c.remarks,
               bp.booking_id, bp.user_id as participant_user_id,
               u.name as user_name, v.name as verifier_name
        FROM checkins c
        JOIN booking_participants bp ON c.booking_participant_id = bp.booking_participant_id
        JOIN users u ON bp.user_id = u.user_id
        LEFT JOIN users v ON c.verified_by = v.user_id
        WHERE 1=1
    """
    params = []
    # If not Admin or Staff, user can only see their own attendance
    if not (current_user.is_admin() or current_user.is_staff()):
        query += " AND bp.user_id = %s"
        params.append(current_user.user_id)

    if booking_id:
        query += " AND bp.booking_id = %s"
        params.append(booking_id)

    query += " ORDER BY c.checkin_time DESC LIMIT 200"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        CheckinResponse(
            checkin_id=r["checkin_id"],
            booking_participant_id=r["booking_participant_id"],
            booking_id=r["booking_id"],
            user_name=r["user_name"],
            verified_by=r["verified_by"],
            verifier_name=r["verifier_name"],
            checkin_time=r["checkin_time"],
            checkout_time=r["checkout_time"],
            status=r["status"],
            remarks=r["remarks"]
        )
        for r in rows
    ]


@router.post("", response_model=CheckinResponse, status_code=status.HTTP_201_CREATED, summary="Check-in participant (Admin/Staff only)")
def checkin_participant(
    req: CheckinCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    # Verify participant and booking status
    db.execute(
        """
        SELECT bp.booking_participant_id, bp.booking_id, bp.user_id, b.status as booking_status, u.name as user_name
        FROM booking_participants bp
        JOIN bookings b ON bp.booking_id = b.booking_id
        JOIN users u ON bp.user_id = u.user_id
        WHERE bp.booking_participant_id = %s
        """,
        (req.booking_participant_id,)
    )
    bp = db.fetchone()
    if not bp:
        raise HTTPException(status_code=404, detail="Booking participant not found.")

    if bp["booking_status"] != "Approved":
        raise HTTPException(status_code=400, detail=f"Cannot check in participant for a {bp['booking_status']} booking. Booking must be Approved.")

    # Check unique constraint
    db.execute("SELECT checkin_id FROM checkins WHERE booking_participant_id = %s", (req.booking_participant_id,))
    if db.fetchone():
        raise HTTPException(status_code=400, detail="Participant has already been checked in or marked.")

    now = datetime.now()
    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            INSERT INTO checkins (booking_participant_id, verified_by, checkin_time, status, remarks)
            VALUES (%s, %s, %s, 'Checked-in', %s)
            """,
            (req.booking_participant_id, current_user.user_id, now, req.remarks)
        )
        cid = cursor.lastrowid

        cursor.execute("UPDATE booking_participants SET attendance_status = 'Attending' WHERE booking_participant_id = %s", (req.booking_participant_id,))

        log_system_audit(
            cursor,
            entity_type="Checkin",
            entity_id=cid,
            action="Checked-in",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"booking_participant_id": req.booking_participant_id, "user_name": bp["user_name"]},
            remarks=f"Participant {bp['user_name']} checked in by {current_user.name}"
        )

    db.execute(
        """
        SELECT c.checkin_id, c.booking_participant_id, c.verified_by, c.checkin_time,
               c.checkout_time, c.status, c.remarks,
               bp.booking_id, u.name as user_name, v.name as verifier_name
        FROM checkins c
        JOIN booking_participants bp ON c.booking_participant_id = bp.booking_participant_id
        JOIN users u ON bp.user_id = u.user_id
        LEFT JOIN users v ON c.verified_by = v.user_id
        WHERE c.checkin_id = %s
        """,
        (cid,)
    )
    row = db.fetchone()

    return CheckinResponse(
        checkin_id=row["checkin_id"],
        booking_participant_id=row["booking_participant_id"],
        booking_id=row["booking_id"],
        user_name=row["user_name"],
        verified_by=row["verified_by"],
        verifier_name=row["verifier_name"],
        checkin_time=row["checkin_time"],
        checkout_time=row["checkout_time"],
        status=row["status"],
        remarks=row["remarks"]
    )


@router.post("/{checkin_id}/checkout", response_model=CheckinResponse, summary="Check out participant (Admin/Staff only)")
def checkout_participant(
    checkin_id: int,
    req: CheckoutRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    db.execute("SELECT checkin_id, status FROM checkins WHERE checkin_id = %s", (checkin_id,))
    existing = db.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Check-in record not found.")
    if existing["status"] != "Checked-in":
        raise HTTPException(status_code=400, detail=f"Cannot check out participant with status '{existing['status']}'. Must be Checked-in.")

    now = datetime.now()
    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            UPDATE checkins
            SET status = 'Checked-out', checkout_time = %s, remarks = COALESCE(%s, remarks)
            WHERE checkin_id = %s
            """,
            (now, req.remarks, checkin_id)
        )

        log_system_audit(
            cursor,
            entity_type="Checkin",
            entity_id=checkin_id,
            action="Checked-out",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"checkout_time": now.isoformat()},
            remarks=f"Checked out by {current_user.name}"
        )

    db.execute(
        """
        SELECT c.checkin_id, c.booking_participant_id, c.verified_by, c.checkin_time,
               c.checkout_time, c.status, c.remarks,
               bp.booking_id, u.name as user_name, v.name as verifier_name
        FROM checkins c
        JOIN booking_participants bp ON c.booking_participant_id = bp.booking_participant_id
        JOIN users u ON bp.user_id = u.user_id
        LEFT JOIN users v ON c.verified_by = v.user_id
        WHERE c.checkin_id = %s
        """,
        (checkin_id,)
    )
    row = db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Check-in record not found")

    return CheckinResponse(
        checkin_id=row["checkin_id"],
        booking_participant_id=row["booking_participant_id"],
        booking_id=row["booking_id"],
        user_name=row["user_name"],
        verified_by=row["verified_by"],
        verifier_name=row["verifier_name"],
        checkin_time=row["checkin_time"],
        checkout_time=row["checkout_time"],
        status=row["status"],
        remarks=row["remarks"]
    )


@router.patch("/{checkin_id}/no-show", response_model=CheckinResponse, summary="Mark participant as No-show (Admin/Staff only)")
def mark_noshow(
    checkin_id: int,
    req: NoShowRequest,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    db.execute("SELECT checkin_id, status FROM checkins WHERE checkin_id = %s", (checkin_id,))
    existing = db.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Check-in record not found.")
    if existing["status"] == "No-show":
        raise HTTPException(status_code=400, detail="Participant has already been marked as No-show.")

    with transaction_scope() as (conn, cursor):
        cursor.execute(
            """
            UPDATE checkins
            SET status = 'No-show', remarks = COALESCE(%s, remarks)
            WHERE checkin_id = %s
            """,
            (req.remarks, checkin_id)
        )
        cursor.execute("SELECT booking_participant_id FROM checkins WHERE checkin_id = %s", (checkin_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Check-in record not found.")

        cursor.execute("UPDATE booking_participants SET attendance_status = 'Declined' WHERE booking_participant_id = %s", (row["booking_participant_id"],))

        log_system_audit(
            cursor,
            entity_type="Checkin",
            entity_id=checkin_id,
            action="No-show",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"status": "No-show"},
            remarks=f"Marked as No-show by {current_user.name}"
        )

    db.execute(
        """
        SELECT c.checkin_id, c.booking_participant_id, c.verified_by, c.checkin_time,
               c.checkout_time, c.status, c.remarks,
               bp.booking_id, u.name as user_name, v.name as verifier_name
        FROM checkins c
        JOIN booking_participants bp ON c.booking_participant_id = bp.booking_participant_id
        JOIN users u ON bp.user_id = u.user_id
        LEFT JOIN users v ON c.verified_by = v.user_id
        WHERE c.checkin_id = %s
        """,
        (checkin_id,)
    )
    row = db.fetchone()

    return CheckinResponse(
        checkin_id=row["checkin_id"],
        booking_participant_id=row["booking_participant_id"],
        booking_id=row["booking_id"],
        user_name=row["user_name"],
        verified_by=row["verified_by"],
        verifier_name=row["verifier_name"],
        checkin_time=row["checkin_time"],
        checkout_time=row["checkout_time"],
        status=row["status"],
        remarks=row["remarks"]
    )
