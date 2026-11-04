import re
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from app.core.config import settings
from app.services.system_settings import get_booking_settings


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_ALIASES = {
    alias: index
    for index, name in enumerate(WEEKDAYS)
    for alias in (name.lower(), name[:3].lower())
}


def campus_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(ZoneInfo(settings.CAMPUS_TIMEZONE)).replace(tzinfo=None)


def campus_now_naive() -> datetime:
    return datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)).replace(tzinfo=None)


def get_day_name(d: date) -> str:
    """Returns capitalized English day name matching database enum (e.g., 'Monday')."""
    return d.strftime("%A")


def _as_time(value) -> Optional[time]:
    if value is None:
        return None
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds()) % (24 * 60 * 60)
        return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _legacy_schedule_for_day(schedule: str, weekday: int):
    range_pattern = re.compile(
        r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
        r"\s*[-–]\s*"
        r"(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
        re.IGNORECASE,
    )
    configured_days = set()
    for match in range_pattern.finditer(schedule):
        first = DAY_ALIASES[match.group(1).lower()]
        last = DAY_ALIASES[match.group(2).lower()]
        day = first
        while True:
            configured_days.add(day)
            if day == last:
                break
            day = (day + 1) % 7

    without_ranges = range_pattern.sub(" ", schedule)
    explicit_days = {
        DAY_ALIASES[match.group(0).lower()]
        for match in re.finditer(
            r"\b(?:monday|mon|tuesday|tue|wednesday|wed|thursday|thu|friday|fri|saturday|sat|sunday|sun)\b",
            without_ranges,
            re.IGNORECASE,
        )
    }
    configured_days.update(explicit_days)
    times = re.findall(
        r"\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:am|pm)?)\b",
        schedule,
        re.IGNORECASE,
    )
    if not times or (configured_days and weekday not in configured_days):
        return None, None, bool(configured_days)
    opens = _as_time(times[0][0])
    closes = _as_time(times[0][1])
    if not opens or not closes or opens == closes:
        return None, None, False
    return opens, closes, True


def _interval_for_day(day: date, opens: time, closes: time):
    start = datetime.combine(day, opens)
    end = datetime.combine(day, closes)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def check_resource_operating_hours(
    cursor,
    resource: Dict[str, Any],
    start_dt: datetime,
    end_dt: datetime,
    locking_read: bool = False,
):
    resource_id = resource["resource_id"]
    lock_clause = " FOR UPDATE" if locking_read else ""
    cursor.execute(
        f"""
        SELECT weekday, is_closed, open_time, close_time, is_active
        FROM resource_operating_hours
        WHERE resource_id = %s
        {lock_clause}
        """,
        (resource_id,),
    )
    all_weekly_rows = cursor.fetchall()
    has_structured_schedule = bool(all_weekly_rows)
    weekly_rows = {
        row["weekday"]: row
        for row in all_weekly_rows
        if row.get("is_active", True)
    }
    cursor.execute(
        f"""
        SELECT start_date, end_date, is_closed, open_time, close_time, reason
        FROM resource_operating_hour_exceptions
        WHERE resource_id = %s
          AND status = 'Active'
          AND start_date <= %s
          AND end_date >= %s
        ORDER BY start_date DESC, exception_id DESC
        {lock_clause}
        """,
        (resource_id, start_dt.date(), start_dt.date()),
    )
    current_exceptions = cursor.fetchall()
    current_exception = current_exceptions[0] if current_exceptions else None
    if current_exception and current_exception["is_closed"]:
        return {
            "is_available": False,
            "reason": (
                f"{resource['resource_name']} is closed from "
                f"{current_exception['start_date']} through {current_exception['end_date']}: "
                f"{current_exception['reason']}."
            ),
        }

    schedule_is_configured = bool(weekly_rows) or (
        not has_structured_schedule and bool(resource.get("operating_hours"))
    )
    if current_exception:
        opens = _as_time(current_exception["open_time"])
        closes = _as_time(current_exception["close_time"])
        schedules = [(start_dt.date(), opens, closes, current_exception["reason"])]
    else:
        schedules = []
        for schedule_day in (start_dt.date() - timedelta(days=1), start_dt.date()):
            weekly_row = weekly_rows.get(schedule_day.weekday())
            if weekly_row:
                if weekly_row["is_closed"]:
                    continue
                opens = _as_time(weekly_row["open_time"])
                closes = _as_time(weekly_row["close_time"])
                schedules.append((schedule_day, opens, closes, None))
            elif weekly_rows or has_structured_schedule:
                continue
            elif resource.get("operating_hours"):
                opens, closes, configured = _legacy_schedule_for_day(
                    resource["operating_hours"], schedule_day.weekday()
                )
                if configured:
                    schedules.append((schedule_day, opens, closes, None))

            if schedule_day != start_dt.date():
                cursor.execute(
                    f"""
                    SELECT start_date, end_date, is_closed, open_time, close_time, reason
                    FROM resource_operating_hour_exceptions
                    WHERE resource_id = %s AND status = 'Active'
                      AND start_date <= %s AND end_date >= %s
                    ORDER BY start_date DESC, exception_id DESC
                    LIMIT 1
                    {lock_clause}
                    """,
                    (resource_id, schedule_day, schedule_day),
                )
                previous_exception = cursor.fetchone()
                if previous_exception:
                    schedules = [item for item in schedules if item[0] != schedule_day]
                    if not previous_exception["is_closed"]:
                        schedules.append((
                            schedule_day,
                            _as_time(previous_exception["open_time"]),
                            _as_time(previous_exception["close_time"]),
                            previous_exception["reason"],
                        ))

    if not schedule_is_configured and not current_exception:
        return {"is_available": True, "reason": ""}

    for schedule_day, opens, closes, _reason in schedules:
        if opens is None or closes is None or opens == closes:
            continue
        interval_start, interval_end = _interval_for_day(schedule_day, opens, closes)
        if interval_start <= start_dt and end_dt <= interval_end:
            return {"is_available": True, "reason": ""}

    if current_exception:
        hours = f"{current_exception['open_time']}–{current_exception['close_time']}"
        reason = f"{resource['resource_name']} is closed at this time. Special operating hours are {hours}: {current_exception['reason']}."
    else:
        weekday = start_dt.weekday()
        weekly_row = weekly_rows.get(weekday)
        legacy_opens, legacy_closes, legacy_configured = (
            (None, None, False)
            if has_structured_schedule
            else _legacy_schedule_for_day(resource.get("operating_hours") or "", weekday)
        )
        if weekly_row and not weekly_row["is_closed"]:
            opens, closes = _as_time(weekly_row["open_time"]), _as_time(weekly_row["close_time"])
            hours = f"{opens.strftime('%I:%M %p').lstrip('0')}–{closes.strftime('%I:%M %p').lstrip('0')}" if opens and closes else "not configured"
            reason = (
                f"Bookings are permitted only between {hours} for {resource['resource_name']}; "
                "these are its normal operating hours."
            )
        elif legacy_configured and legacy_opens and legacy_closes:
            hours = f"{legacy_opens.strftime('%I:%M %p').lstrip('0')}–{legacy_closes.strftime('%I:%M %p').lstrip('0')}"
            reason = (
                f"Bookings are permitted only between {hours} for {resource['resource_name']}; "
                "these are its normal operating hours."
            )
        else:
            reason = f"{resource['resource_name']} is closed on {get_day_name(start_dt.date())}."
    return {"is_available": False, "reason": reason}


def check_resource_availability(
    cursor,
    resource_id: int,
    start_dt: datetime,
    end_dt: datetime,
    exclude_booking_id: Optional[int] = None,
    booking_settings: Optional[Dict[str, Any]] = None,
    locking_read: bool = False,
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
    cursor.execute(
        "SELECT resource_id, resource_name, status, operating_hours FROM resources WHERE resource_id = %s"
        + (" FOR UPDATE" if locking_read else ""),
        (resource_id,),
    )
    res = cursor.fetchone()
    if not res:
        return {"is_available": False, "state": "blocked", "reason": f"Resource ID {resource_id} not found."}

    if res["status"] != "Available":
        return {
            "is_available": False,
            "state": "maintenance" if res["status"] == "Maintenance" else "blocked",
            "reason": f"Resource '{res['resource_name']}' is currently marked {res['status']} and cannot be booked."
        }

    operating = check_resource_operating_hours(cursor, res, start_dt, end_dt, locking_read)
    if not operating["is_available"]:
        return {
            "is_available": False,
            "state": "outside_operating_hours",
            "reason": operating["reason"],
        }

    # 2. Blackout periods check (maintenance or campus holidays)
    cursor.execute(
        f"""
        SELECT blackout_id, reason, start_datetime, end_datetime, maintenance_id,
               reason_category, reason_explanation
        FROM resource_blackout_periods
        WHERE resource_id = %s
          AND status = 'Active'
          AND start_datetime < %s
          AND end_datetime > %s
        LIMIT 1
        {"FOR UPDATE" if locking_read else ""}
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
            f"""
            SELECT timetable_id, subject_name, department_name, section, start_time, end_time, class_type, academic_year
            FROM resource_timetable
            WHERE resource_id = %s
              AND day_of_week = %s
              AND start_time < %s
              AND end_time > %s
              AND (academic_year = %s OR academic_year IS NULL)
            ORDER BY start_time ASC
            {"FOR UPDATE" if locking_read else ""}
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

    booking_query += " LIMIT 1" + (" FOR UPDATE" if locking_read else "")
    cursor.execute(booking_query, tuple(params))
    clash = cursor.fetchone()

    if clash:
        clash_start_str = clash["start_time"].strftime("%b %d, %I:%M %p") if hasattr(clash["start_time"], "strftime") else str(clash["start_time"])
        clash_end_str = clash["end_time"].strftime("%I:%M %p") if hasattr(clash["end_time"], "strftime") else str(clash["end_time"])
        return {
            "is_available": False,
            "state": "taken",
            "reason": (
                f"{res['resource_name']} is already reserved from {clash_start_str} to {clash_end_str}. "
                f"Your requested time overlaps with that reservation."
            ),
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
