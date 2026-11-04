from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.maintenance import MaintenanceCreate, MaintenanceComplete, MaintenanceResponse
from app.services.booking_workflow import create_notification
from app.services.audit_service import log_system_audit
from app.services.availability import campus_datetime, campus_now_naive

router = APIRouter()


@router.get("", response_model=List[MaintenanceResponse], summary="List maintenance records (Admin/Staff)")
def list_maintenance(
    status: Optional[str] = Query(None),
    resource_id: Optional[int] = Query(None),
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    query = """
        SELECT m.maintenance_id, m.resource_id, m.item_id, m.reported_by, m.assigned_to,
               m.issue_description, m.maintenance_type, m.status, m.reported_at, m.resolved_at, m.remarks,
               r.resource_name, eq.item_name, u.name as reporter_name
        FROM maintenance_records m
        LEFT JOIN resources r ON m.resource_id = r.resource_id
        LEFT JOIN equipment_items eq ON m.item_id = eq.item_id
        JOIN users u ON m.reported_by = u.user_id
        WHERE 1=1
    """
    params = []
    if status and status != "All":
        query += " AND m.status = %s"
        params.append(status)
    if resource_id:
        query += " AND m.resource_id = %s"
        params.append(resource_id)

    query += " ORDER BY m.reported_at DESC"
    db.execute(query, tuple(params))
    rows = db.fetchall()

    return [
        MaintenanceResponse(
            maintenance_id=r["maintenance_id"],
            resource_id=r["resource_id"],
            resource_name=r["resource_name"],
            item_id=r["item_id"],
            item_name=r["item_name"],
            reported_by=r["reported_by"],
            reporter_name=r["reporter_name"],
            assigned_to=r["assigned_to"],
            issue_description=r["issue_description"],
            maintenance_type=r["maintenance_type"],
            status=r["status"],
            reported_at=r["reported_at"],
            resolved_at=r["resolved_at"],
            remarks=r["remarks"]
        )
        for r in rows
    ]


@router.post("", response_model=MaintenanceResponse, status_code=status.HTTP_201_CREATED, summary="Create maintenance record (Admin/Staff)")
def create_maintenance(
    req: MaintenanceCreate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    if not req.resource_id and not req.item_id:
        raise HTTPException(status_code=400, detail="Must specify either resource_id or item_id for maintenance.")

    with transaction_scope() as (conn, cursor):
        try:
            start_value = (
                datetime.fromisoformat(req.start_datetime.replace("Z", "+00:00"))
                if req.start_datetime else campus_now_naive()
            )
            end_value = (
                datetime.fromisoformat(req.end_datetime.replace("Z", "+00:00"))
                if req.end_datetime else datetime(2099, 12, 31, 23, 59, 59)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Maintenance start and end must be valid date/time values.") from exc
        start_dt = campus_datetime(start_value)
        end_dt = campus_datetime(end_value)
        if end_dt <= start_dt:
            raise HTTPException(status_code=422, detail="Maintenance end time must be after its start time.")

        affected_bookings = []
        if req.resource_id:
            cursor.execute(
                "SELECT resource_id, resource_name FROM resources WHERE resource_id = %s FOR UPDATE",
                (req.resource_id,),
            )
            target_resource = cursor.fetchone()
            if not target_resource:
                raise HTTPException(status_code=404, detail="Resource not found.")
            cursor.execute(
                """
                SELECT DISTINCT b.booking_id, b.user_id, u.name AS requester_name, b.purpose,
                       b.status AS booking_status, br.start_time, br.end_time
                FROM bookings b
                JOIN booking_resources br ON b.booking_id = br.booking_id
                JOIN users u ON u.user_id = b.user_id
                WHERE br.resource_id = %s
                  AND br.status IN ('Approved', 'Pending')
                  AND b.status IN ('Approved', 'Pending')
                  AND br.start_time < %s
                  AND br.end_time > %s
                ORDER BY br.start_time, b.booking_id
                """,
                (req.resource_id, end_dt, start_dt),
            )
            affected_bookings = cursor.fetchall()
            if affected_bookings and not req.confirm_booking_conflicts:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "Existing bookings overlap this maintenance period. Review the affected bookings before confirming.",
                        "requires_confirmation": True,
                        "resource_name": target_resource["resource_name"],
                        "conflict_count": len(affected_bookings),
                        "conflicts": [
                            {
                                "booking_id": row["booking_id"],
                                "requester_name": row["requester_name"],
                                "purpose": row["purpose"],
                                "status": row["booking_status"],
                                "start_time": row["start_time"].isoformat(),
                                "end_time": row["end_time"].isoformat(),
                            }
                            for row in affected_bookings
                        ],
                    },
                )

        # 1. Insert maintenance record
        cursor.execute(
            """
            INSERT INTO maintenance_records
                (resource_id, item_id, reported_by, issue_description, maintenance_type, status, remarks)
            VALUES (%s, %s, %s, %s, %s, 'Open', %s)
            """,
            (
                req.resource_id, req.item_id, current_user.user_id, req.issue_description,
                req.maintenance_type, req.remarks,
            )
        )
        maint_id = cursor.lastrowid

        # 2. Update resource or equipment status
        if req.resource_id:
            if start_dt <= campus_now_naive() < end_dt:
                cursor.execute("UPDATE resources SET status = 'Maintenance' WHERE resource_id = %s", (req.resource_id,))
            cursor.execute("SELECT resource_name FROM resources WHERE resource_id = %s", (req.resource_id,))
            res_name = cursor.fetchone()["resource_name"]

            # 3. Create resource blackout period with explicit maintenance_id foreign key
            cursor.execute(
                """
                INSERT INTO resource_blackout_periods
                    (resource_id, maintenance_id, start_datetime, end_datetime, reason, reason_category,
                     reason_explanation, created_by)
                VALUES (%s, %s, %s, %s, %s, 'Maintenance', %s, %s)
                """,
                (
                    req.resource_id, maint_id, start_dt, end_dt,
                    f"{req.maintenance_type}: {req.issue_description}", req.issue_description,
                    current_user.user_id,
                )
            )

            # Confirmed conflicts remain in booking history and are not cancelled automatically.
            for ab in affected_bookings:
                create_notification(
                    cursor,
                    user_id=ab["user_id"],
                    message=f"Maintenance ({req.maintenance_type}) is scheduled for '{res_name}' during booking BK-{ab['booking_id']}. Contact administration to resolve this conflict; your booking was not cancelled.",
                    notif_type="Alert",
                    booking_id=ab["booking_id"]
                )

        if req.item_id:
            cursor.execute("UPDATE equipment_items SET availability_status = 'Maintenance' WHERE item_id = %s", (req.item_id,))

        cursor.execute(
            "SELECT user_id FROM users WHERE role = 'Admin' AND is_active = 1 AND user_id != %s",
            (current_user.user_id,)
        )
        affected_admins = cursor.fetchall()
        affected_item = res_name if req.resource_id else None
        if req.item_id:
            cursor.execute("SELECT item_name FROM equipment_items WHERE item_id = %s", (req.item_id,))
            equipment = cursor.fetchone()
            affected_item = equipment["item_name"] if equipment else "Equipment"
        for admin in affected_admins:
            create_notification(
                cursor,
                user_id=admin["user_id"],
                message=f"New maintenance ticket #{maint_id} for {affected_item or 'campus equipment'}: {req.issue_description}",
                notif_type="Alert",
                audience="Admin"
            )

        log_system_audit(
            cursor,
            entity_type="Maintenance",
            entity_id=maint_id,
            action="Created",
            changed_by=current_user.user_id,
            old_values=None,
            new_values={"resource_id": req.resource_id, "item_id": req.item_id, "issue": req.issue_description},
            remarks=f"Maintenance logged by {current_user.name}"
        )

    db.execute(
        """
        SELECT m.maintenance_id, m.resource_id, m.item_id, m.reported_by, m.assigned_to,
               m.issue_description, m.maintenance_type, m.status, m.reported_at, m.resolved_at, m.remarks,
               r.resource_name, eq.item_name, u.name as reporter_name
        FROM maintenance_records m
        LEFT JOIN resources r ON m.resource_id = r.resource_id
        LEFT JOIN equipment_items eq ON m.item_id = eq.item_id
        JOIN users u ON m.reported_by = u.user_id
        WHERE m.maintenance_id = %s
        """,
        (maint_id,)
    )
    row = db.fetchone()

    return MaintenanceResponse(
        maintenance_id=row["maintenance_id"],
        resource_id=row["resource_id"],
        resource_name=row["resource_name"],
        item_id=row["item_id"],
        item_name=row["item_name"],
        reported_by=row["reported_by"],
        reporter_name=row["reporter_name"],
        assigned_to=row["assigned_to"],
        issue_description=row["issue_description"],
        maintenance_type=row["maintenance_type"],
        status=row["status"],
        reported_at=row["reported_at"],
        resolved_at=row["resolved_at"],
        remarks=row["remarks"]
    )


@router.patch("/{maintenance_id}/complete", response_model=MaintenanceResponse, summary="Mark maintenance complete (Admin/Staff)")
def complete_maintenance(
    maintenance_id: int,
    req: MaintenanceComplete,
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    db.execute("SELECT * FROM maintenance_records WHERE maintenance_id = %s", (maintenance_id,))
    m = db.fetchone()
    if not m:
        raise HTTPException(status_code=404, detail="Maintenance record not found")
    if m["status"] == "Resolved":
        raise HTTPException(status_code=400, detail="This maintenance record has already been marked as Resolved.")

    with transaction_scope() as (conn, cursor):
        now = datetime.now()
        cursor.execute(
            """
            UPDATE maintenance_records
            SET status = 'Resolved', resolved_at = %s, remarks = %s
            WHERE maintenance_id = %s
            """,
            (now, req.remarks, maintenance_id)
        )

        # Remove ONLY its own associated blackout period using foreign key maintenance_id
        cursor.execute(
            "DELETE FROM resource_blackout_periods WHERE maintenance_id = %s",
            (maintenance_id,)
        )

        # Restore resource if no other open maintenance records exist for it
        if m["resource_id"]:
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM maintenance_records WHERE resource_id = %s AND status != 'Resolved' AND maintenance_id != %s",
                (m["resource_id"], maintenance_id)
            )
            other_open = cursor.fetchone()["cnt"]
            if other_open == 0:
                cursor.execute("UPDATE resources SET status = 'Available' WHERE resource_id = %s", (m["resource_id"],))

        # Restore equipment item only if no other open maintenance records exist for it
        if m["item_id"]:
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM maintenance_records WHERE item_id = %s AND status != 'Resolved' AND maintenance_id != %s",
                (m["item_id"], maintenance_id)
            )
            other_eq_maint = cursor.fetchone()["cnt"]
            if other_eq_maint == 0:
                cursor.execute("UPDATE equipment_items SET availability_status = 'Available', condition_status = 'Good' WHERE item_id = %s", (m["item_id"],))

        log_system_audit(
            cursor,
            entity_type="Maintenance",
            entity_id=maintenance_id,
            action="Resolved",
            changed_by=current_user.user_id,
            old_values={"status": m["status"]},
            new_values={"status": "Resolved", "remarks": req.remarks},
            remarks=f"Maintenance marked resolved by {current_user.name}"
        )

    db.execute(
        """
        SELECT m.maintenance_id, m.resource_id, m.item_id, m.reported_by, m.assigned_to,
               m.issue_description, m.maintenance_type, m.status, m.reported_at, m.resolved_at, m.remarks,
               r.resource_name, eq.item_name, u.name as reporter_name
        FROM maintenance_records m
        LEFT JOIN resources r ON m.resource_id = r.resource_id
        LEFT JOIN equipment_items eq ON m.item_id = eq.item_id
        JOIN users u ON m.reported_by = u.user_id
        WHERE m.maintenance_id = %s
        """,
        (maintenance_id,)
    )
    row = db.fetchone()

    return MaintenanceResponse(
        maintenance_id=row["maintenance_id"],
        resource_id=row["resource_id"],
        resource_name=row["resource_name"],
        item_id=row["item_id"],
        item_name=row["item_name"],
        reported_by=row["reported_by"],
        reporter_name=row["reporter_name"],
        assigned_to=row["assigned_to"],
        issue_description=row["issue_description"],
        maintenance_type=row["maintenance_type"],
        status=row["status"],
        reported_at=row["reported_at"],
        resolved_at=row["resolved_at"],
        remarks=row["remarks"]
    )
