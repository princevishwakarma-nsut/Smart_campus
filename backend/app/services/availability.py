from datetime import datetime, date, time
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.services.system_settings import get_booking_settings


def get_day_name(d: date) -> str:
    """Returns capitalized English day name matching database enum (e.g., 'Monday')."""
    return d.strftime("%A")


def check_resource_availability(
    cursor,
    resource_id: int,
    start_dt: datetime,
    end_dt: datetime,
    exclude_booking_id: Optional[int] = None,
    booking_settings: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Availability Engine:
    1. Operational status
    2. Midnight crossing validation
    3. Maintenance blackout periods
    4. Recurring academic timetable (academic year 2026-2027)
    5. Existing Pending and Approved bookings (interval overlap)
    """
    # 0. Reject bookings spanning across midnight
    if start_dt.date() != end_dt.date():
        return {
            "is_available": False,
            "state": "blocked",
            "reason": "Bookings spanning across midnight are not permitted. Please submit separate single-day reservations."
        }

    # 1. Operational status check
    cursor.execute("SELECT resource_id, resource_name, status FROM resources WHERE resource_id = %s", (resource_id,))
    res = cursor.fetchone()
    if not res:
        return {"is_available": False, "state": "blocked", "reason": f"Resource ID {resource_id} not found."}

    if res["status"] != "Available":
        return {
            "is_available": False,
            "state": "maintenance" if res["status"] == "Maintenance" else "blocked",
            "reason": f"Resource '{res['resource_name']}' is currently marked {res['status']} and cannot be booked."
        }

    # 2. Blackout periods check (maintenance or campus holidays)
    cursor.execute(
        """
        SELECT blackout_id, reason, start_datetime, end_datetime, maintenance_id,
               reason_category, reason_explanation
        FROM resource_blackout_periods
        WHERE resource_id = %s
          AND status = 'Active'
          AND start_datetime < %s
          AND end_datetime > %s
        LIMIT 1
        """,
        (resource_id, end_dt, start_dt)
    )
    blackout = cursor.fetchone()
    if blackout:
        reason_category = blackout.get("reason_category") or "Other"
        reason_text = blackout.get("reason_explanation") or blackout.get("reason") or "Scheduled blackout"
        overlap_start = max(start_dt, blackout["start_datetime"])
        overlap_end = min(end_dt, blackout["end_datetime"])
        date_time_format = "%Y-%m-%d %I:%M %p"
        return {
            "is_available": False,
            "state": "blocked",
            "reason": (
                f"{res['resource_name']} cannot be booked for the requested period "
                f"{start_dt.strftime(date_time_format)} to {end_dt.strftime(date_time_format)}. "
                f"It is unavailable during the overlapping blackout period "
                f"{overlap_start.strftime(date_time_format)} to {overlap_end.strftime(date_time_format)} "
                f"(full blackout: {blackout['start_datetime'].strftime(date_time_format)} to "
                f"{blackout['end_datetime'].strftime(date_time_format)}). "
                f"Reason category: {reason_category}. Details: {reason_text}"
            ),
            "conflicting_blackout": blackout
        }

    # 3. Recurring academic timetable check for the configured academic year
    configured = booking_settings or get_booking_settings(cursor)
    timetable_conflicts = []
    if configured["timetable_enforcement"]:
        day_name = get_day_name(start_dt.date())
        req_start_time = start_dt.time()
        req_end_time = end_dt.time()
        cursor.execute(
            """
            SELECT timetable_id, subject_name, department_name, section, start_time, end_time, class_type, academic_year
            FROM resource_timetable
            WHERE resource_id = %s
              AND day_of_week = %s
              AND start_time < %s
              AND end_time > %s
              AND (academic_year = %s OR academic_year IS NULL)
            ORDER BY start_time ASC
            """,
            (resource_id, day_name, req_end_time, req_start_time, configured["academic_year"])
        )
        timetable_conflicts = cursor.fetchall()
    if timetable_conflicts:
        primary_conflict = timetable_conflicts[0]
        subj = primary_conflict.get("subject_name", "Academic Class")
        dept = primary_conflict.get("department_name", "")
        sec = primary_conflict.get("section", "")
        ctype = primary_conflict.get("class_type", "Class")
        ayear = primary_conflict.get("academic_year", "2026-2027")

        conflict_msg = f"Academic timetable conflict: {subj} ({dept} {sec} - {ctype}, AY {ayear})"
        if len(timetable_conflicts) > 1:
            conflict_msg += f" plus {len(timetable_conflicts) - 1} overlapping schedule entry."

        return {
            "is_available": False,
            "state": "timetable_conflict",
            "reason": conflict_msg,
            "conflicting_timetable": primary_conflict,
            "all_timetable_conflicts": timetable_conflicts
        }

    # 4. Existing Pending and Approved bookings check (Interval overlap logic)
    # Overlap occurs when: existing_start < requested_end AND existing_end > requested_start
    booking_query = """
        SELECT br.booking_resource_id, br.booking_id, br.start_time, br.end_time, br.status, b.purpose, b.user_id
        FROM booking_resources br
        JOIN bookings b ON br.booking_id = b.booking_id
        WHERE br.resource_id = %s
          AND br.status IN ('Approved', 'Pending')
          AND br.start_time < %s
          AND br.end_time > %s
    """
    params = [resource_id, end_dt, start_dt]
    if exclude_booking_id:
        booking_query += " AND br.booking_id != %s"
        params.append(exclude_booking_id)

    booking_query += " LIMIT 1"
    cursor.execute(booking_query, tuple(params))
    clash = cursor.fetchone()

    if clash:
        clash_start_str = clash["start_time"].strftime("%Y-%m-%d %H:%M") if hasattr(clash["start_time"], "strftime") else str(clash["start_time"])
        clash_end_str = clash["end_time"].strftime("%H:%M") if hasattr(clash["end_time"], "strftime") else str(clash["end_time"])
        return {
            "is_available": False,
            "state": "taken",
            "reason": f"Overlaps {clash['status'].lower()} booking BK-{clash['booking_id']} ({clash_start_str} - {clash_end_str}).",
            "conflicting_booking": clash
        }

    return {"is_available": True, "state": "free", "reason": ""}


def get_resource_schedule_for_day(cursor, resource_id: int, query_date: date) -> Dict[str, Any]:
    """Retrieve all bookings, timetable slots, and blackouts for a resource on a specific day."""
    day_name = get_day_name(query_date)
    day_start = datetime.combine(query_date, time(0, 0, 0))
    day_end = datetime.combine(query_date, time(23, 59, 59))

    # Timetable slots
    cursor.execute(
        """
        SELECT timetable_id, subject_name, department_name, section, start_time, end_time, class_type, academic_year
        FROM resource_timetable
        WHERE resource_id = %s AND day_of_week = %s
        ORDER BY start_time ASC
        """,
        (resource_id, day_name)
    )
    raw_tt = cursor.fetchall()
    timetable_slots = []
    for tt in raw_tt:
        timetable_slots.append({
            "type": "timetable",
            "title": f"{tt['subject_name']} ({tt['department_name']} {tt['section']})",
            "start": str(tt["start_time"]),
            "end": str(tt["end_time"]),
            "status": "Class",
            "academic_year": tt.get("academic_year", "2026-2027")
        })

    # Bookings
    cursor.execute(
        """
        SELECT br.booking_id, br.start_time, br.end_time, br.status, b.purpose, u.name as user_name
        FROM booking_resources br
        JOIN bookings b ON br.booking_id = b.booking_id
        LEFT JOIN users u ON b.user_id = u.user_id
        WHERE br.resource_id = %s
          AND br.status IN ('Approved', 'Pending')
          AND br.start_time <= %s
          AND br.end_time >= %s
        ORDER BY br.start_time ASC
        """,
        (resource_id, day_end, day_start)
    )
    raw_bk = cursor.fetchall()
    booking_slots = []
    for bk in raw_bk:
        booking_slots.append({
            "type": "booking",
            "booking_id": bk["booking_id"],
            "title": bk["purpose"],
            "user_name": bk.get("user_name", ""),
            "start": bk["start_time"].isoformat() if hasattr(bk["start_time"], "isoformat") else str(bk["start_time"]),
            "end": bk["end_time"].isoformat() if hasattr(bk["end_time"], "isoformat") else str(bk["end_time"]),
            "status": bk["status"]
        })

    # Blackouts
    cursor.execute(
        """
        SELECT blackout_id, reason, start_datetime, end_datetime
        FROM resource_blackout_periods
        WHERE resource_id = %s
          AND status = 'Active'
          AND start_datetime <= %s
          AND end_datetime >= %s
        ORDER BY start_datetime ASC
        """,
        (resource_id, day_end, day_start)
    )
    raw_bo = cursor.fetchall()
    blackout_slots = []
    for bo in raw_bo:
        blackout_slots.append({
            "type": "blackout",
            "blackout_id": bo["blackout_id"],
            "reason": bo["reason"],
            "start": bo["start_datetime"].isoformat() if hasattr(bo["start_datetime"], "isoformat") else str(bo["start_datetime"]),
            "end": bo["end_datetime"].isoformat() if hasattr(bo["end_datetime"], "isoformat") else str(bo["end_datetime"])
        })

    return {
        "date": query_date.isoformat(),
        "day_of_week": day_name,
        "timetable_slots": timetable_slots,
        "booking_slots": booking_slots,
        "blackout_slots": blackout_slots
    }
