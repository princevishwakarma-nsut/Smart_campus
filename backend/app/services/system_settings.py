import json


DEFAULT_BOOKING_SETTINGS = {
    "academic_year": "2026-2027",
    "timetable_enforcement": True,
    "booking_window_days": 30,
    "approval_mode": "Manual",
    "approval_categories": [],
    "min_booking_minutes": 15,
    "max_booking_minutes": 480,
    "cancellation_cutoff_hours": 0
}


def get_booking_settings(cursor):
    cursor.execute(
        """
        SELECT academic_year, timetable_enforcement, booking_window_days,
               approval_mode, approval_categories, min_booking_minutes,
               max_booking_minutes, cancellation_cutoff_hours
        FROM system_settings
        WHERE setting_id = 1
        """
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("Runtime booking settings are missing; apply database migration 008.")

    settings = dict(row)
    categories = settings.get("approval_categories")
    if isinstance(categories, str):
        categories = json.loads(categories)
    settings["approval_categories"] = categories or []
    settings["timetable_enforcement"] = bool(settings["timetable_enforcement"])
    return settings
