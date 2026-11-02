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
    # Resource metrics
    db.execute("SELECT COUNT(*) as total FROM resources")
    total_resources = db.fetchone()["total"]

    # Calculate dynamically true available spaces right now (not under maintenance, blackout, or occupied by active booking)
    db.execute(
        """
        SELECT COUNT(*) as avail FROM resources r
        WHERE r.status = 'Available'
          AND r.resource_id NOT IN (
            SELECT resource_id FROM resource_blackout_periods WHERE start_datetime <= NOW() AND end_datetime >= NOW()
          )
          AND r.resource_id NOT IN (
            SELECT resource_id FROM booking_resources WHERE status IN ('Approved', 'Pending') AND start_time <= NOW() AND end_time >= NOW()
          )
        """
    )
    available_resources = db.fetchone()["avail"]

    db.execute("SELECT COUNT(*) as maint FROM resources WHERE status = 'Maintenance'")
    maintenance_resources = db.fetchone()["maint"]

    date_filter = ""
    date_params = []
    if start_date:
        date_filter += " AND DATE(start_time) >= %s"
        date_params.append(start_date)
    if end_date:
        date_filter += " AND DATE(start_time) <= %s"
        date_params.append(end_date)

    def count_bookings(where_clause="1=1", params=()):
        db.execute(
            f"SELECT COUNT(*) AS count FROM bookings WHERE {where_clause}{date_filter}",
            tuple(params) + tuple(date_params)
        )
        return db.fetchone()["count"]

    total_bookings = count_bookings()
    pending_approvals = count_bookings("status = %s", ("Pending",))
    approved_bookings = count_bookings("status = %s", ("Approved",))
    rejected_bookings = count_bookings("status = %s", ("Rejected",))
    cancelled_bookings = count_bookings("status = %s", ("Cancelled",))
    bookings_today = count_bookings("DATE(start_time) = CURDATE()")

    db.execute("SELECT COUNT(*) AS total_types, COALESCE(SUM(total_quantity), 0) AS total_units FROM equipment_items WHERE is_active = 1")
    equipment_inventory = db.fetchone()
    db.execute("SELECT COUNT(*) AS count FROM maintenance_records WHERE status NOT IN ('Resolved', 'Completed', 'Cancelled')")
    maintenance_tickets = db.fetchone()["count"]

    # User & Society metrics
    db.execute("SELECT COUNT(*) as active FROM users WHERE is_active = 1")
    active_users = db.fetchone()["active"]

    db.execute("SELECT COUNT(*) as total FROM societies WHERE is_active = 1")
    total_societies = db.fetchone()["total"]

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
    current_user: UserContext = Depends(require_roles(Role.ADMIN)),
    db=Depends(get_db)
):
    """
    Unified append-only audit trail combining:
    1. booking_audit (Booking lifecycle events)
    2. system_audit (Resource, Equipment, Society, User, Maintenance, Blackout events)
    """
    results = []

    # 1. Booking Audit Query
    b_query = """
        SELECT a.audit_id, a.booking_id, a.changed_by, a.action,
               a.old_values, a.new_values, a.remarks, a.changed_at,
               u.name as changed_by_name, u.role as changed_by_role,
               b.purpose as booking_purpose, 'Booking' as entity_type, a.booking_id as entity_id
        FROM booking_audit a
        LEFT JOIN users u ON a.changed_by = u.user_id
        LEFT JOIN bookings b ON a.booking_id = b.booking_id
        WHERE 1=1
    """
    b_params = []
    if action and action != "All":
        b_query += " AND a.action = %s"
        b_params.append(action)
    if q:
        b_query += " AND (a.remarks LIKE %s OR u.name LIKE %s OR b.purpose LIKE %s)"
        b_params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    b_query += " ORDER BY a.changed_at DESC LIMIT 100"
    db.execute(b_query, tuple(b_params))
    for r in db.fetchall():
        results.append({
            "id": f"BA-{r['audit_id']}",
            "audit_id": r["audit_id"],
            "entity_type": "Booking",
            "entity_id": r["entity_id"],
            "booking_id": f"BK-{r['booking_id']}",
            "raw_booking_id": r["booking_id"],
            "booking_purpose": r.get("booking_purpose"),
            "action": r["action"],
            "old_values": r["old_values"],
            "new_values": r["new_values"],
            "changed_by": r.get("changed_by_name") or "System",
            "changed_by_role": r.get("changed_by_role") or "System",
            "changed_at": r["changed_at"].isoformat() if hasattr(r["changed_at"], "isoformat") else str(r["changed_at"]),
            "remarks": r["remarks"]
        })

    # 2. System Audit Query (Only if not filtering specifically for booking only)
    if not entity_type or entity_type != "Booking":
        s_query = """
            SELECT sa.audit_id, sa.entity_type, sa.entity_id, sa.action, sa.changed_by,
                   sa.old_values, sa.new_values, sa.remarks, sa.created_at,
                   u.name as changed_by_name, u.role as changed_by_role
            FROM system_audit sa
            LEFT JOIN users u ON sa.changed_by = u.user_id
            WHERE 1=1
        """
        s_params = []
        if action and action != "All":
            s_query += " AND sa.action = %s"
            s_params.append(action)
        if entity_type and entity_type != "All":
            s_query += " AND sa.entity_type = %s"
            s_params.append(entity_type)
        if q:
            s_query += " AND (sa.remarks LIKE %s OR u.name LIKE %s OR sa.entity_type LIKE %s)"
            s_params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

        s_query += " ORDER BY sa.created_at DESC LIMIT 100"
        db.execute(s_query, tuple(s_params))
        for r in db.fetchall():
            results.append({
                "id": f"SA-{r['audit_id']}",
                "audit_id": r["audit_id"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "booking_id": None,
                "raw_booking_id": None,
                "booking_purpose": None,
                "action": r["action"],
                "old_values": r["old_values"],
                "new_values": r["new_values"],
                "changed_by": r.get("changed_by_name") or "System",
                "changed_by_role": r.get("changed_by_role") or "System",
                "changed_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                "remarks": r["remarks"]
            })

    # Sort combined results chronologically descending
    results.sort(key=lambda x: x["changed_at"], reverse=True)
    return results[:150]


@router.get("/settings", summary="Get live backend system configuration (Admin)")
@router.get("/settings/", include_in_schema=False)
def get_live_settings(current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    configured = get_booking_settings(db)
    db.execute("SELECT DATABASE()")
    current_db = db.fetchone()["DATABASE()"]

    db.execute(
        "SELECT COUNT(*) as count FROM resource_timetable WHERE academic_year = %s OR academic_year IS NULL",
        (configured["academic_year"],)
    )
    tt_count = db.fetchone()["count"]

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
