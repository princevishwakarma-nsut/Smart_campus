import json
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.config import settings
from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.database.transaction import transaction_scope
from app.schemas.report import DashboardStatsResponse, UtilizationReportResponse, SystemSettingsUpdate
from app.services.audit_service import log_system_audit
from app.services.system_settings import get_booking_settings

router = APIRouter()


@router.get("/dashboard", response_model=DashboardStatsResponse, summary="Get dashboard summary metrics (Admin/Staff)")
def get_dashboard_stats(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db=Depends(get_db)
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="Dashboard start date must be on or before its end date.")
    # Resource metrics (consolidated single query)
    db.execute(
        """
        SELECT 
            COUNT(*) as total,
            COALESCE(SUM(CASE WHEN status = 'Maintenance' THEN 1 ELSE 0 END), 0) as maint,
            COALESCE(SUM(CASE WHEN status = 'Available'
                AND resource_id NOT IN (
                    SELECT resource_id FROM resource_blackout_periods WHERE start_datetime <= NOW() AND end_datetime >= NOW()
                )
                AND resource_id NOT IN (
                    SELECT resource_id FROM booking_resources WHERE status IN ('Approved', 'Pending') AND start_time <= NOW() AND end_time >= NOW()
                ) THEN 1 ELSE 0 END), 0) as avail
        FROM resources
        """
    )
    r_counts = db.fetchone()
    total_resources = r_counts["total"]
    available_resources = r_counts["avail"]
    maintenance_resources = r_counts["maint"]

    date_filter = ""
    date_params = []
    if start_date:
        date_filter += " AND DATE(start_time) >= %s"
        date_params.append(start_date)
    if end_date:
        date_filter += " AND DATE(start_time) <= %s"
        date_params.append(end_date)

    # Booking metrics (consolidated single query instead of 6 sequential queries)
    db.execute(
        f"""
        SELECT 
            COUNT(*) AS total_bookings,
            COALESCE(SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END), 0) AS pending_approvals,
            COALESCE(SUM(CASE WHEN status = 'Approved' THEN 1 ELSE 0 END), 0) AS approved_bookings,
            COALESCE(SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END), 0) AS rejected_bookings,
            COALESCE(SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END), 0) AS cancelled_bookings,
            COALESCE(SUM(CASE WHEN DATE(start_time) = CURDATE() THEN 1 ELSE 0 END), 0) AS bookings_today
        FROM bookings
        WHERE 1=1 {date_filter}
        """,
        tuple(date_params)
    )
    b_counts = db.fetchone()
    total_bookings = b_counts["total_bookings"]
    pending_approvals = b_counts["pending_approvals"]
    approved_bookings = b_counts["approved_bookings"]
    rejected_bookings = b_counts["rejected_bookings"]
    cancelled_bookings = b_counts["cancelled_bookings"]
    bookings_today = b_counts["bookings_today"]

    # System metrics: equipment, maintenance, users, societies (consolidated single query)
    db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM equipment_items WHERE is_active = 1) AS total_types,
            (SELECT COALESCE(SUM(total_quantity), 0) FROM equipment_items WHERE is_active = 1) AS total_units,
            (SELECT COUNT(*) FROM maintenance_records WHERE status NOT IN ('Resolved', 'Completed', 'Cancelled')) AS maintenance_tickets,
            (SELECT COUNT(*) FROM users WHERE is_active = 1) AS active_users,
            (SELECT COUNT(*) FROM societies WHERE is_active = 1) AS total_societies
        """
    )
    sys_metrics = db.fetchone()
    equipment_inventory = {"total_types": sys_metrics["total_types"], "total_units": sys_metrics["total_units"]}
    maintenance_tickets = sys_metrics["maintenance_tickets"]
    active_users = sys_metrics["active_users"]
    total_societies = sys_metrics["total_societies"]

    # Category distribution
    db.execute(
        """
        SELECT c.category_name, COUNT(r.resource_id) as resource_count
        FROM categories c
        LEFT JOIN resources r ON c.category_id = r.category_id
        GROUP BY c.category_id, c.category_name
        ORDER BY resource_count DESC
        """
    )
    category_distribution = db.fetchall()

    # Upcoming bookings
    db.execute(
        f"""
        SELECT b.booking_id, b.purpose, b.status, b.start_time, b.end_time,
               COALESCE(
                 (SELECT GROUP_CONCAT(DISTINCT r.resource_name ORDER BY r.resource_name SEPARATOR ', ')
                  FROM booking_resources br JOIN resources r ON r.resource_id = br.resource_id
                  WHERE br.booking_id = b.booking_id),
                 (SELECT GROUP_CONCAT(DISTINCT ei.item_name ORDER BY ei.item_name SEPARATOR ', ')
                  FROM booking_equipment_items bei JOIN equipment_items ei ON ei.item_id = bei.item_id
                  WHERE bei.booking_id = b.booking_id),
                 'Equipment reservation'
               ) AS resource_name,
               u.name AS user_name
        FROM bookings b
        JOIN users u ON b.user_id = u.user_id
        WHERE b.start_time >= NOW() AND b.status IN ('Approved', 'Pending')
        ORDER BY b.start_time ASC
        LIMIT 6
        """
    )
    raw_upcoming = db.fetchall()
    upcoming_bookings = []
    for ub in raw_upcoming:
        upcoming_bookings.append({
            "booking_id": ub["booking_id"],
            "purpose": ub["purpose"],
            "status": ub["status"],
            "resource_name": ub["resource_name"],
            "user_name": ub["user_name"],
            "start_time": ub["start_time"].isoformat() if hasattr(ub["start_time"], "isoformat") else str(ub["start_time"]),
            "end_time": ub["end_time"].isoformat() if hasattr(ub["end_time"], "isoformat") else str(ub["end_time"])
        })

    db.execute(
        """
        SELECT ba.booking_id, ba.action, ba.remarks, ba.changed_at,
               b.purpose, u.name AS actor_name
        FROM booking_audit ba
        LEFT JOIN bookings b ON b.booking_id = ba.booking_id
        LEFT JOIN users u ON u.user_id = ba.changed_by
        WHERE (%s IS NULL OR DATE(ba.changed_at) >= %s)
          AND (%s IS NULL OR DATE(ba.changed_at) <= %s)
        ORDER BY ba.changed_at DESC
        LIMIT 6
        """,
        (start_date, start_date, end_date, end_date)
    )
    recent_activity = [
        {
            "booking_id": row["booking_id"],
            "action": row["action"],
            "remarks": row["remarks"],
            "purpose": row["purpose"],
            "actor_name": row["actor_name"] or "System",
            "changed_at": row["changed_at"].isoformat() if hasattr(row["changed_at"], "isoformat") else str(row["changed_at"])
        }
        for row in db.fetchall()
    ]

    return DashboardStatsResponse(
        total_resources=total_resources,
        available_resources=available_resources,
        maintenance_resources=maintenance_resources,
        total_bookings=total_bookings,
        pending_approvals=pending_approvals,
        approved_bookings=approved_bookings,
        rejected_bookings=rejected_bookings,
        cancelled_bookings=cancelled_bookings,
        active_users=active_users,
        total_societies=total_societies,
        upcoming_bookings=upcoming_bookings,
        category_distribution=category_distribution,
        equipment_types=equipment_inventory["total_types"],
        equipment_units=equipment_inventory["total_units"],
        maintenance_tickets=maintenance_tickets,
        bookings_today=bookings_today,
        recent_activity=recent_activity
    )


@router.get("/resource-utilization", response_model=UtilizationReportResponse, summary="Get resource utilization analytics")
def get_resource_utilization(current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF)), db=Depends(get_db)):
    # Total hours booked
    db.execute(
        """
        SELECT COALESCE(SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)) / 60.0, 0) as total_hours
        FROM booking_resources
        WHERE status = 'Approved'
        """
    )
    total_hours = float(db.fetchone()["total_hours"] or 0)

    # Busiest resources
    db.execute(
        """
        SELECT r.resource_name, r.resource_code, c.category_name,
               COUNT(br.booking_resource_id) as booking_count,
               COALESCE(SUM(TIMESTAMPDIFF(MINUTE, br.start_time, br.end_time)) / 60.0, 0) as hours_booked
        FROM resources r
        JOIN categories c ON r.category_id = c.category_id
        LEFT JOIN booking_resources br ON r.resource_id = br.resource_id AND br.status = 'Approved'
        GROUP BY r.resource_id, r.resource_name, r.resource_code, c.category_name
        ORDER BY booking_count DESC, hours_booked DESC
        LIMIT 10
        """
    )
    busiest_resources = db.fetchall()

    # Peak hours distribution
    db.execute(
        """
        SELECT HOUR(start_time) as hour, COUNT(*) as count
        FROM booking_resources
        GROUP BY HOUR(start_time)
        ORDER BY hour ASC
        """
    )
    peak_hours = db.fetchall()

    # Status breakdown
    db.execute("SELECT status, COUNT(*) as cnt FROM bookings GROUP BY status")
    status_rows = db.fetchall()
    status_breakdown = {r["status"]: r["cnt"] for r in status_rows}

    return UtilizationReportResponse(
        total_hours_booked=round(total_hours, 1),
        busiest_resources=busiest_resources,
        peak_hours=peak_hours,
        status_breakdown=status_breakdown
    )


@router.get("/audit", summary="Get system & booking audit trail (Admin only)")
def get_audit_trail(
    q: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=300),
    offset: int = Query(0, ge=0),
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    """
    Unified append-only audit trail combining booking and system audit records.
    Uses a single UNION ALL query with server-side pagination to avoid loading
    large batches and to keep the audit log responsive.
    """
    booking_filters = []
    booking_params = []
    if action and action != "All":
        booking_filters.append("a.action = %s")
        booking_params.append(action)
    if q:
        booking_filters.append("(a.remarks LIKE %s OR u.name LIKE %s OR b.purpose LIKE %s)")
        like_q = f"%{q}%"
        booking_params.extend([like_q, like_q, like_q])

    system_filters = []
    system_params = []
    if action and action != "All":
        system_filters.append("sa.action = %s")
        system_params.append(action)
    if entity_type and entity_type != "All":
        system_filters.append("sa.entity_type = %s")
        system_params.append(entity_type)
    if q:
        system_filters.append("(sa.remarks LIKE %s OR u.name LIKE %s OR sa.entity_type LIKE %s)")
        like_q = f"%{q}%"
        system_params.extend([like_q, like_q, like_q])

    union_query = """
        SELECT
            a.audit_id AS audit_id,
            a.booking_id AS entity_id,
            'Booking' AS entity_type,
            a.booking_id AS raw_booking_id,
            a.action AS action,
            a.remarks AS remarks,
            a.old_values AS old_values,
            a.new_values AS new_values,
            a.changed_at AS changed_at,
            u.name AS changed_by_name,
            u.role AS changed_by_role,
            b.purpose AS booking_purpose,
            a.booking_id AS booking_id
        FROM booking_audit a
        LEFT JOIN users u ON a.changed_by = u.user_id
        LEFT JOIN bookings b ON a.booking_id = b.booking_id
        WHERE 1=1
    """
    if booking_filters:
        union_query += " AND " + " AND ".join(booking_filters)

    if not entity_type or entity_type != "Booking":
        union_query += """
            UNION ALL
            SELECT
                sa.audit_id AS audit_id,
                sa.entity_id AS entity_id,
                sa.entity_type AS entity_type,
                NULL AS raw_booking_id,
                sa.action AS action,
                sa.remarks AS remarks,
                sa.old_values AS old_values,
                sa.new_values AS new_values,
                sa.created_at AS changed_at,
                u.name AS changed_by_name,
                u.role AS changed_by_role,
                NULL AS booking_purpose,
                NULL AS booking_id
            FROM system_audit sa
            LEFT JOIN users u ON sa.changed_by = u.user_id
            WHERE 1=1
        """
        if system_filters:
            union_query += " AND " + " AND ".join(system_filters)

    union_query += " ORDER BY changed_at DESC, audit_id DESC LIMIT %s OFFSET %s"
    db.execute(union_query, tuple(booking_params + system_params + [limit, offset]))

    results = []
    for row in db.fetchall():
        prefix = "BA" if row["entity_type"] == "Booking" else "SA"
        results.append({
            "id": f"{prefix}-{row['audit_id']}",
            "audit_id": row["audit_id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "booking_id": f"BK-{row['raw_booking_id']}" if row.get("raw_booking_id") is not None else None,
            "raw_booking_id": row.get("raw_booking_id"),
            "booking_purpose": row.get("booking_purpose"),
            "action": row["action"],
            "old_values": row["old_values"],
            "new_values": row["new_values"],
            "changed_by": row.get("changed_by_name") or "System",
            "changed_by_role": row.get("changed_by_role") or "System",
            "changed_at": row["changed_at"].isoformat() if hasattr(row["changed_at"], "isoformat") else str(row["changed_at"]),
            "remarks": row["remarks"],
        })

    return results


@router.get("/settings", summary="Get live backend system configuration (Admin)")
@router.get("/settings/", include_in_schema=False)
def get_live_settings(current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    configured = get_booking_settings(db)
    db.execute(
        "SELECT DATABASE() AS current_db, (SELECT COUNT(*) FROM resource_timetable WHERE academic_year = %s OR academic_year IS NULL) AS tt_count",
        (configured["academic_year"],)
    )
    meta_row = db.fetchone()
    current_db = meta_row["current_db"]
    tt_count = meta_row["tt_count"]

    db.execute(
        """
        SELECT category_name AS name FROM categories
        UNION
        SELECT DISTINCT category AS name FROM equipment_items WHERE category IS NOT NULL AND category != ''
        ORDER BY name
        """
    )
    categories = [row["name"] for row in db.fetchall()]
    return {
        **configured,
        "categories": categories,
        "database_connected": True,
        "database_name": current_db,
        "database_pool": settings.DB_POOL_NAME,
        "database_pool_size": settings.DB_POOL_SIZE,
        "timetable_entries_active": tt_count,
        "token_expire_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        "environment": settings.ENVIRONMENT
    }


@router.put("/settings", summary="Update persisted booking rules (Admin)")
def update_live_settings(
    payload: SystemSettingsUpdate,
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    if payload.min_booking_minutes > payload.max_booking_minutes:
        raise HTTPException(status_code=422, detail="Minimum booking duration cannot exceed the maximum.")
    db.execute(
        """
        SELECT category_name AS name FROM categories
        UNION
        SELECT DISTINCT category AS name FROM equipment_items WHERE category IS NOT NULL AND category != ''
        """
    )
    known_categories = {row["name"] for row in db.fetchall()}
    unknown_categories = set(payload.approval_categories) - known_categories
    if unknown_categories:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown approval categories: {', '.join(sorted(unknown_categories))}."
        )

    with transaction_scope() as (_, cursor):
        cursor.execute(
            """
            SELECT academic_year, timetable_enforcement, booking_window_days,
                   approval_mode, approval_categories, min_booking_minutes,
                   max_booking_minutes, cancellation_cutoff_hours
            FROM system_settings WHERE setting_id = 1 FOR UPDATE
            """
        )
        previous = cursor.fetchone()
        if not previous:
            raise RuntimeError("Runtime booking settings are missing; apply database migration 008.")

        updated = payload.model_dump()
        cursor.execute(
            """
            UPDATE system_settings
            SET academic_year = %s, timetable_enforcement = %s, booking_window_days = %s,
                approval_mode = %s, approval_categories = %s, min_booking_minutes = %s,
                max_booking_minutes = %s, cancellation_cutoff_hours = %s, updated_by = %s
            WHERE setting_id = 1
            """,
            (
                updated["academic_year"], updated["timetable_enforcement"],
                updated["booking_window_days"], updated["approval_mode"],
                json.dumps(updated["approval_categories"]),
                updated["min_booking_minutes"], updated["max_booking_minutes"],
                updated["cancellation_cutoff_hours"], current_user.user_id
            )
        )
        log_system_audit(
            cursor,
            entity_type="Settings",
            entity_id=1,
            action="Updated",
            changed_by=current_user.user_id,
            old_values=previous,
            new_values=updated,
            remarks="Booking rules updated by administrator."
        )
    return {"message": "Booking settings saved.", **updated}
