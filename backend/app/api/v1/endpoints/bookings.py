from typing import List, Optional
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import get_current_user, UserContext, Role
from app.core.config import settings
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.booking import (
    BookingCreate,
    BookingCancelRequest,
    BookingResponse,
    BookingResourceResponse,
    BookingEquipmentResponse
)
from app.services.booking_workflow import create_booking_transaction, create_notification
from app.services.audit_service import log_booking_audit
from app.services.system_settings import get_booking_settings

router = APIRouter()


def format_booking_row(b, resources, equipment_map=None):
    if equipment_map is None:
        equipment_map = {}

    eq_list = []
    for eq in equipment_map.get(b["booking_id"], []):
        eq_list.append(
            BookingEquipmentResponse(
                booking_equipment_id=eq.get("booking_equipment_id"),
                item_id=eq["item_id"],
                item_code=eq.get("item_code"),
                item_name=eq.get("item_name"),
                category=eq.get("category"),
                unit=eq.get("unit") or "Piece",
                requested_quantity=eq.get("requested_quantity", 1),
                approved_quantity=eq.get("approved_quantity", 0),
                issued_quantity=eq.get("issued_quantity", 0),
                returned_good_quantity=eq.get("returned_good_quantity", 0),
                returned_damaged_quantity=eq.get("returned_damaged_quantity", 0),
                lost_quantity=eq.get("lost_quantity", 0),
                location=eq.get("location") or "Gym"
            )
        )

    res_list = [
        BookingResourceResponse(
            booking_resource_id=r["booking_resource_id"],
            resource_id=r["resource_id"],
            resource_name=r.get("resource_name"),
            resource_code=r.get("resource_code"),
            location=r.get("location"),
            start_time=r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
            end_time=r["end_time"].isoformat() if hasattr(r["end_time"], "isoformat") else str(r["end_time"]),
            status=r["status"]
        )
        for r in resources.get(b["booking_id"], [])
    ]

    start_str = None
    if b.get("start_time"):
        start_str = b["start_time"].isoformat() if hasattr(b["start_time"], "isoformat") else str(b["start_time"])
    elif res_list:
        start_str = res_list[0].start_time

    end_str = None
    if b.get("end_time"):
        end_str = b["end_time"].isoformat() if hasattr(b["end_time"], "isoformat") else str(b["end_time"])
    elif res_list:
        end_str = res_list[0].end_time

    return BookingResponse(
        booking_id=b["booking_id"],
        user_id=b["user_id"],
        user_name=b.get("user_name"),
        user_email=b.get("user_email"),
        society_id=b.get("society_id"),
        society_name=b.get("club_name"),
        purpose=b["purpose"],
        expected_participants=b["expected_participants"],
        status=b["status"],
        start_time=start_str,
        end_time=end_str,
        created_at=b["created_at"],
        updated_at=b["updated_at"],
        resources=res_list,
        equipment=eq_list,
        decided_by=b.get("decided_by"),
        remarks=b.get("remarks")
    )


@router.get("", response_model=List[BookingResponse], summary="List bookings")
def list_bookings(
    status: Optional[str] = Query(None),
    resource_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    query = """
        SELECT b.booking_id, b.user_id, b.society_id, b.purpose, b.expected_participants,
               b.status, b.start_time, b.end_time, b.created_at, b.updated_at,
               u.name as user_name, u.email as user_email,
               s.club_name,
               (SELECT u2.name FROM booking_approvals ba JOIN users u2 ON ba.approver_id = u2.user_id WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) as decided_by,
               (SELECT ba.remarks FROM booking_approvals ba WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) as remarks
        FROM bookings b
        JOIN users u ON b.user_id = u.user_id
        LEFT JOIN societies s ON b.society_id = s.club_id
        WHERE 1=1
    """
    params = []
    # If not admin or staff, restrict to user's bookings
    if not (current_user.is_admin() or current_user.is_staff()):
        query += " AND b.user_id = %s"
        params.append(current_user.user_id)
    elif user_id:
        query += " AND b.user_id = %s"
        params.append(user_id)

    if isinstance(status, str) and status and status != "All":
        query += " AND b.status = %s"
        params.append(status)

    query += " ORDER BY b.created_at DESC LIMIT 500"
    db.execute(query, tuple(params))
    bookings = db.fetchall()

    if not bookings:
        return []

    # Fetch resources for these bookings
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

    # Fetch equipment items for these bookings
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


@router.get("/page", summary="Search and page bookings")
def page_bookings(
    status_filter: Optional[str] = Query(None, alias="status"),
    booking_type: str = Query("All", pattern="^(All|Space|Equipment|Combined)$"),
    category_id: Optional[int] = Query(None, ge=1),
    q: Optional[str] = Query(None, max_length=200),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_by: str = Query("created_desc", pattern="^(created_desc|created_asc|start_asc|start_desc)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="Booking start date must be on or before its end date.")

    where = ["1=1"]
    params = []
    if not (current_user.is_admin() or current_user.is_staff()):
        where.append("b.user_id = %s")
        params.append(current_user.user_id)
    if status_filter and status_filter != "All":
        where.append("b.status = %s")
        params.append(status_filter)
    if booking_type == "Space":
        where.append("EXISTS (SELECT 1 FROM booking_resources br WHERE br.booking_id = b.booking_id)")
        where.append("NOT EXISTS (SELECT 1 FROM booking_equipment_items bei WHERE bei.booking_id = b.booking_id)")
    elif booking_type == "Equipment":
        where.append("EXISTS (SELECT 1 FROM booking_equipment_items bei WHERE bei.booking_id = b.booking_id)")
        where.append("NOT EXISTS (SELECT 1 FROM booking_resources br WHERE br.booking_id = b.booking_id)")
    elif booking_type == "Combined":
        where.append("EXISTS (SELECT 1 FROM booking_resources br WHERE br.booking_id = b.booking_id)")
        where.append("EXISTS (SELECT 1 FROM booking_equipment_items bei WHERE bei.booking_id = b.booking_id)")
    if category_id:
        where.append(
            """EXISTS (
                SELECT 1 FROM booking_resources br
                JOIN resources r ON r.resource_id = br.resource_id
                WHERE br.booking_id = b.booking_id AND r.category_id = %s
            )"""
        )
        params.append(category_id)
    if start_date:
        where.append("b.start_time >= %s")
        params.append(datetime.combine(start_date, time.min))
    if end_date:
        where.append("b.start_time < %s")
        params.append(datetime.combine(end_date + timedelta(days=1), time.min))
    if q and q.strip():
        search = f"%{q.strip()}%"
        where.append(
            """
            (b.purpose LIKE %s OR u.name LIKE %s OR u.email LIKE %s
             OR EXISTS (
               SELECT 1 FROM booking_resources br
               JOIN resources r ON r.resource_id = br.resource_id
               WHERE br.booking_id = b.booking_id AND r.resource_name LIKE %s
             )
             OR EXISTS (
               SELECT 1 FROM booking_equipment_items be
               JOIN equipment_items ei ON ei.item_id = be.item_id
               WHERE be.booking_id = b.booking_id AND ei.item_name LIKE %s
             ))
            """
        )
        params.extend([search] * 5)
    where_sql = " AND ".join(where)

    db.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM bookings b JOIN users u ON u.user_id = b.user_id
        WHERE {where_sql}
        """,
        tuple(params)
    )
    total = db.fetchone()["total"]
    order_by = {
        "created_desc": "b.created_at DESC, b.booking_id DESC",
        "created_asc": "b.created_at ASC, b.booking_id ASC",
        "start_asc": "b.start_time ASC, b.booking_id ASC",
        "start_desc": "b.start_time DESC, b.booking_id DESC"
    }[sort_by]
    db.execute(
        f"""
        SELECT b.booking_id, b.user_id, b.society_id, b.purpose, b.expected_participants,
               b.status, b.start_time, b.end_time, b.created_at, b.updated_at,
               u.name AS user_name, u.email AS user_email, s.club_name,
               (SELECT u2.name FROM booking_approvals ba JOIN users u2 ON ba.approver_id = u2.user_id
                WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) AS decided_by,
               (SELECT ba.remarks FROM booking_approvals ba
                WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) AS remarks
        FROM bookings b JOIN users u ON u.user_id = b.user_id
        LEFT JOIN societies s ON s.club_id = b.society_id
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset])
    )
    bookings = db.fetchall()
    booking_ids = [booking["booking_id"] for booking in bookings]
    resource_map = {}
    equipment_map = {}
    if booking_ids:
        placeholders = ",".join(["%s"] * len(booking_ids))
        db.execute(
            f"""
            SELECT br.booking_resource_id, br.booking_id, br.resource_id, br.start_time, br.end_time, br.status,
                   r.resource_name, r.resource_code, r.location
            FROM booking_resources br JOIN resources r ON r.resource_id = br.resource_id
            WHERE br.booking_id IN ({placeholders})
            """,
            tuple(booking_ids)
        )
        for resource in db.fetchall():
            resource_map.setdefault(resource["booking_id"], []).append(resource)
        db.execute(
            f"""
            SELECT be.booking_equipment_id, be.booking_id, be.item_id,
                   be.requested_quantity, be.approved_quantity, be.issued_quantity,
                   be.returned_good_quantity, be.returned_damaged_quantity, be.lost_quantity,
                   ei.item_name, ei.item_code, ei.category, ei.unit, ei.location
            FROM booking_equipment_items be JOIN equipment_items ei ON ei.item_id = be.item_id
            WHERE be.booking_id IN ({placeholders})
            """,
            tuple(booking_ids)
        )
        for equipment in db.fetchall():
            equipment_map.setdefault(equipment["booking_id"], []).append(equipment)
    return {
        "items": [
            format_booking_row(booking, resource_map, equipment_map)
            for booking in bookings
        ],
        "total": total,
        "offset": offset,
        "limit": limit
    }


@router.get("/my", response_model=List[BookingResponse], summary="Get current user's bookings")
def get_my_bookings(current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    return list_bookings(status=None, resource_id=None, user_id=current_user.user_id, current_user=current_user, db=db)


@router.get("/my/schedule", summary="Get current user's approved bookings for today and later")
def get_my_schedule(current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    timezone = ZoneInfo(settings.CAMPUS_TIMEZONE)
    now = datetime.now(timezone)
    today = now.date()
    current_time = now.replace(tzinfo=None)
    next_day_start = datetime.combine(today + timedelta(days=1), time.min)

    base_query = """
        SELECT b.booking_id, b.user_id, b.society_id, b.purpose, b.expected_participants,
               b.status, b.start_time, b.end_time, b.created_at, b.updated_at,
               u.name AS user_name, u.email AS user_email, s.club_name,
               (SELECT u2.name FROM booking_approvals ba JOIN users u2 ON u2.user_id = ba.approver_id
                WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) AS decided_by,
               (SELECT ba.remarks FROM booking_approvals ba
                WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) AS remarks
        FROM bookings b
        JOIN users u ON u.user_id = b.user_id
        LEFT JOIN societies s ON s.club_id = b.society_id
        WHERE b.user_id = %s AND b.status = 'Approved' AND {schedule_filter}
        ORDER BY b.start_time ASC, b.booking_id ASC
    """

    def load_bookings(schedule_filter, filter_params):
        db.execute(base_query.format(schedule_filter=schedule_filter), (current_user.user_id, *filter_params))
        bookings = db.fetchall()
        booking_ids = [booking["booking_id"] for booking in bookings]
        resource_map = {}
        equipment_map = {}
        if booking_ids:
            placeholders = ",".join(["%s"] * len(booking_ids))
            db.execute(
                f"""
                SELECT br.booking_resource_id, br.booking_id, br.resource_id, br.start_time,
                       br.end_time, br.status, r.resource_name, r.resource_code, r.location
                FROM booking_resources br JOIN resources r ON r.resource_id = br.resource_id
                WHERE br.booking_id IN ({placeholders})
                ORDER BY br.start_time ASC
                """,
                tuple(booking_ids)
            )
            for resource in db.fetchall():
                resource_map.setdefault(resource["booking_id"], []).append(resource)
            db.execute(
                f"""
                SELECT be.booking_equipment_id, be.booking_id, be.item_id,
                       be.requested_quantity, be.approved_quantity, be.issued_quantity,
                       be.returned_good_quantity, be.returned_damaged_quantity, be.lost_quantity,
                       ei.item_name, ei.item_code, ei.category, ei.unit, ei.location
                FROM booking_equipment_items be JOIN equipment_items ei ON ei.item_id = be.item_id
                WHERE be.booking_id IN ({placeholders})
                ORDER BY ei.item_name ASC
                """,
                tuple(booking_ids)
            )
            for equipment in db.fetchall():
                equipment_map.setdefault(equipment["booking_id"], []).append(equipment)
        return [format_booking_row(booking, resource_map, equipment_map) for booking in bookings]

    today_bookings = load_bookings(
        "b.start_time < %s AND b.end_time > %s",
        (next_day_start, current_time)
    )
    upcoming_bookings = load_bookings(
        "b.start_time >= %s",
        (next_day_start,)
    )
    return {
        "today": today.isoformat(),
        "timezone": settings.CAMPUS_TIMEZONE,
        "today_bookings": today_bookings,
        "upcoming_bookings": upcoming_bookings
    }


@router.get("/{booking_id}", response_model=BookingResponse, summary="Get booking details")
def get_booking(booking_id: int, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    db.execute(
        """
        SELECT b.booking_id, b.user_id, b.society_id, b.purpose, b.expected_participants,
               b.status, b.start_time, b.end_time, b.created_at, b.updated_at,
               u.name as user_name, u.email as user_email,
               s.club_name,
               (SELECT u2.name FROM booking_approvals ba JOIN users u2 ON ba.approver_id = u2.user_id WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) as decided_by,
               (SELECT ba.remarks FROM booking_approvals ba WHERE ba.booking_id = b.booking_id ORDER BY ba.approval_id DESC LIMIT 1) as remarks
        FROM bookings b
        JOIN users u ON b.user_id = u.user_id
        LEFT JOIN societies s ON b.society_id = s.club_id
        WHERE b.booking_id = %s
        """,
        (booking_id,)
    )
    b = db.fetchone()
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not (current_user.is_admin() or current_user.is_staff()) and b["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Cannot access booking belonging to another user.")

    db.execute(
        """
        SELECT br.booking_resource_id, br.booking_id, br.resource_id, br.start_time, br.end_time, br.status,
               r.resource_name, r.resource_code, r.location
        FROM booking_resources br
        JOIN resources r ON br.resource_id = r.resource_id
        WHERE br.booking_id = %s
        """,
        (booking_id,)
    )
    resources = {booking_id: db.fetchall()}

    db.execute(
        """
        SELECT be.booking_equipment_id, be.booking_id, be.item_id,
               be.requested_quantity, be.approved_quantity, be.issued_quantity,
               be.returned_good_quantity, be.returned_damaged_quantity, be.lost_quantity,
               eq.item_name, eq.item_code, eq.category, eq.unit, eq.location
        FROM booking_equipment_items be
        JOIN equipment_items eq ON be.item_id = eq.item_id
        WHERE be.booking_id = %s
        """,
        (booking_id,)
    )
    equipment_map = {booking_id: db.fetchall()}

    return format_booking_row(b, resources, equipment_map)


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED, summary="Create a new booking")
def create_booking(req: BookingCreate, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    resources_list = []
    if req.resources:
        for r in req.resources:
            resources_list.append({"resource_id": r.resource_id, "start_time": r.start_time, "end_time": r.end_time})
    elif req.resource_id and (req.start_time or req.start_datetime) and (req.end_time or req.end_datetime):
        s_time = req.start_time or req.start_datetime
        e_time = req.end_time or req.end_datetime
        resources_list.append({"resource_id": req.resource_id, "start_time": s_time, "end_time": e_time})

    # Equipment requests
    eq_reqs = None
    if req.equipment_requests:
        eq_reqs = [{"item_id": eq.item_id, "quantity": eq.quantity} for eq in req.equipment_requests]
    elif req.equipment_ids:
        eq_reqs = [{"item_id": eid, "quantity": 1} for eid in req.equipment_ids]

    b_start = req.start_time or req.start_datetime
    b_end = req.end_time or req.end_datetime

    if not resources_list and not eq_reqs:
        raise HTTPException(
            status_code=400,
            detail="Booking must include at least one campus resource or equipment item."
        )

    if not resources_list and eq_reqs:
        if not b_start or not b_end:
            raise HTTPException(
                status_code=400,
                detail="Equipment-only booking must specify start_time and end_time."
            )

    participants = [p.user_id for p in req.participants] if req.participants else []

    with transaction_scope() as (conn, cursor):
        booking_id = create_booking_transaction(
            conn=conn,
            cursor=cursor,
            user_id=current_user.user_id,
            user_role=current_user.role,
            purpose=req.purpose,
            resources_list=resources_list,
            expected_participants=req.expected_participants or 1,
            society_id=req.society_id,
            participants=participants,
            equipment_requests=eq_reqs,
            equipment_ids=req.equipment_ids,
            booking_start_time=b_start,
            booking_end_time=b_end
        )

    return get_booking(booking_id, current_user, db)


@router.patch("/{booking_id}/cancel", response_model=BookingResponse, summary="Cancel booking")
@router.post("/{booking_id}/cancel", response_model=BookingResponse, summary="Cancel booking (alias)")
def cancel_booking(booking_id: int, req: BookingCancelRequest, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    db.execute("SELECT user_id, status, purpose, start_time FROM bookings WHERE booking_id = %s", (booking_id,))
    b = db.fetchone()
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not current_user.is_admin() and b["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Cannot cancel another user's booking.")

    if b["status"] in ("Cancelled", "Rejected"):
        raise HTTPException(status_code=400, detail=f"Booking is already {b['status']}.")
    if not current_user.is_admin():
        policy = get_booking_settings(db)
        if policy["cancellation_cutoff_hours"] and b["start_time"]:
            cutoff = b["start_time"] - datetime.now()
            if cutoff.total_seconds() <= policy["cancellation_cutoff_hours"] * 3600:
                raise HTTPException(
                    status_code=400,
                    detail=f"Bookings cannot be cancelled within {policy['cancellation_cutoff_hours']} hours of their start time."
                )

    with transaction_scope() as (conn, cursor):
        cursor.execute("UPDATE bookings SET status = 'Cancelled' WHERE booking_id = %s", (booking_id,))
        cursor.execute("UPDATE booking_resources SET status = 'Cancelled' WHERE booking_id = %s", (booking_id,))

        # Release any booked equipment only if not damaged or under maintenance
        cursor.execute("SELECT item_id FROM booking_equipment_items WHERE booking_id = %s", (booking_id,))
        for eq in cursor.fetchall():
            cursor.execute(
                """
                UPDATE equipment_items
                SET availability_status = 'Available'
                WHERE item_id = %s AND availability_status = 'Issued' AND condition_status != 'Damaged'
                """,
                (eq["item_id"],)
            )

        # Append-only audit & notification
        log_booking_audit(
            cursor,
            booking_id=booking_id,
            changed_by=current_user.user_id,
            action="Cancelled",
            old_values={"status": b["status"]},
            new_values={"status": "Cancelled"},
            remarks=req.remarks or "Cancelled by user"
        )
        create_notification(
            cursor,
            user_id=b["user_id"],
            message=f"Booking BK-{booking_id} ('{b['purpose']}') was cancelled. Reason: {req.remarks}",
            notif_type="Alert",
            booking_id=booking_id
        )
        cursor.execute("SELECT name FROM users WHERE user_id = %s", (b["user_id"],))
        requester = cursor.fetchone()
        requester_name = requester["name"] if requester else f"User #{b['user_id']}"
        cursor.execute("SELECT user_id FROM users WHERE role = 'Admin' AND is_active = 1 AND user_id != %s", (current_user.user_id,))
        for admin in cursor.fetchall():
            create_notification(
                cursor,
                user_id=admin["user_id"],
                message=f"Booking BK-{booking_id} for '{b['purpose']}' was cancelled by {current_user.name or requester_name}.",
                notif_type="Alert",
                booking_id=booking_id,
                audience="Admin"
            )

    return get_booking(booking_id, current_user, db)
