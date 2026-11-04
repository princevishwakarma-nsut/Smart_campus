import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.core.config import settings
from app.schemas.blackout import (
    BlackoutConflictPreview,
    BlackoutSelection,
    EquipmentBlackoutConflictPreview,
    EquipmentBlackoutCreate,
)


def campus_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(ZoneInfo(settings.CAMPUS_TIMEZONE)).replace(tzinfo=None)


def campus_now_naive() -> datetime:
    return datetime.now(ZoneInfo(settings.CAMPUS_TIMEZONE)).replace(tzinfo=None)


def resolve_resources(
    cursor,
    resource_ids: Sequence[int],
    category_ids: Sequence[int],
    excluded_resource_ids: Sequence[int] = (),
    lock: bool = False
) -> List[Dict]:
    resource_ids = sorted(set(resource_ids))
    category_ids = sorted(set(category_ids))
    excluded_resource_ids = sorted(set(excluded_resource_ids))
    if not resource_ids and not category_ids:
        raise HTTPException(status_code=422, detail="Select at least one resource or resource category.")

    if category_ids:
        cursor.execute(
            f"SELECT category_id FROM categories WHERE category_id IN ({','.join(['%s'] * len(category_ids))})",
            tuple(category_ids)
        )
        valid_categories = {row["category_id"] for row in cursor.fetchall()}
        invalid_categories = sorted(set(category_ids) - valid_categories)
        if invalid_categories:
            raise HTTPException(status_code=404, detail=f"Resource categories not found: {invalid_categories}.")

    conditions = []
    params: List[int] = []
    if resource_ids:
        conditions.append(f"r.resource_id IN ({','.join(['%s'] * len(resource_ids))})")
        params.extend(resource_ids)
    if category_ids:
        conditions.append(
            f"(r.category_id IN ({','.join(['%s'] * len(category_ids))}) AND UPPER(TRIM(r.status)) = 'AVAILABLE')"
        )
        params.extend(category_ids)
    if excluded_resource_ids:
        exclusions = f" AND r.resource_id NOT IN ({','.join(['%s'] * len(excluded_resource_ids))})"
        params.extend(excluded_resource_ids)
    else:
        exclusions = ""

    query = f"""
        SELECT r.resource_id, r.resource_name, r.category_id, r.status, c.category_name
        FROM resources r
        JOIN categories c ON c.category_id = r.category_id
        WHERE ({' OR '.join(conditions)}){exclusions}
        ORDER BY r.resource_id
        {"FOR UPDATE" if lock else ""}
    """
    cursor.execute(query, tuple(params))
    resources = cursor.fetchall()
    found_ids = {row["resource_id"] for row in resources}
    missing_ids = sorted(set(resource_ids) - found_ids)
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Resources not found: {missing_ids}.")
    unavailable = [
        f"{row['resource_name']} ({row['status']})"
        for row in resources
        if row["resource_id"] in resource_ids and str(row["status"]).strip().casefold() != "available"
    ]
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Every selected resource must be active and available: {', '.join(unavailable)}."
        )
    if not resources:
        raise HTTPException(status_code=422, detail="The selected categories contain no available resources.")
    return resources


def find_booking_conflicts(
    cursor,
    resource_ids: Sequence[int],
    start_datetime: datetime,
    end_datetime: datetime,
    locking_read: bool = False,
) -> List[Dict]:
    resource_ids = sorted(set(resource_ids))
    if not resource_ids:
        return []
    params: List = [*resource_ids, end_datetime, start_datetime]
    query = f"""
        SELECT br.booking_id, br.resource_id, r.resource_name, b.user_id,
               u.name AS requester_name, br.start_time, br.end_time,
               br.status AS resource_status, b.status AS booking_status, b.purpose
        FROM booking_resources br
        JOIN bookings b ON b.booking_id = br.booking_id
        JOIN users u ON u.user_id = b.user_id
        JOIN resources r ON r.resource_id = br.resource_id
        WHERE br.resource_id IN ({','.join(['%s'] * len(resource_ids))})
          AND br.status IN ('Pending', 'Approved')
          AND b.status IN ('Pending', 'Approved')
          AND br.start_time < %s
          AND br.end_time > %s
    """
    query += " ORDER BY r.resource_name, br.start_time, br.booking_id"
    if locking_read:
        query += " FOR UPDATE"
    cursor.execute(query, tuple(params))
    return cursor.fetchall()


def conflict_payload(conflicts: List[Dict]) -> List[Dict]:
    payload = []
    for row in conflicts:
        item = {
            "booking_id": row["booking_id"],
            "resource_id": row["resource_id"],
            "resource_name": row["resource_name"],
            "requester_name": row["requester_name"],
            "start_time": row["start_time"].isoformat(),
            "end_time": row["end_time"].isoformat(),
            "status": row["booking_status"],
            "purpose": row["purpose"],
        }
        if row.get("blackout_start_datetime"):
            item["blackout_start_datetime"] = row["blackout_start_datetime"].isoformat()
            item["blackout_end_datetime"] = row["blackout_end_datetime"].isoformat()
        payload.append(item)
    return payload


def notify_other_admins_of_conflicts(cursor, actor_id: int, conflicts: List[Dict], start: datetime, end: datetime):
    cursor.execute(
        "SELECT user_id FROM users WHERE role = 'Admin' AND is_active = 1 AND user_id != %s",
        (actor_id,)
    )
    admins = cursor.fetchall()
    for conflict in conflicts:
        message = (
            f"Blackout conflict: {conflict['resource_name']} requested by "
            f"{conflict['requester_name']} has booking BK-{conflict['booking_id']} "
            f"from {conflict['start_time']:%Y-%m-%d %H:%M} to {conflict['end_time']:%Y-%m-%d %H:%M}. "
            f"Proposed blackout: {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}."
        )
        for admin in admins:
            cursor.execute(
                """
                SELECT notification_id FROM notifications
                WHERE user_id = %s AND audience = 'Admin' AND booking_id = %s AND message = %s
                  AND created_at >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)
                LIMIT 1
                """,
                (admin["user_id"], conflict["booking_id"], message)
            )
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO notifications (user_id, booking_id, message, type, audience, is_read)
                    VALUES (%s, %s, %s, 'Alert', 'Admin', 0)
                    """,
                    (admin["user_id"], conflict["booking_id"], message)
                )


def notify_users_of_confirmed_blackout_conflicts(
    cursor,
    conflicts: List[Dict],
    start: datetime,
    end: datetime,
    reason: str,
) -> None:
    notified_bookings = set()
    for conflict in conflicts:
        booking_id = conflict["booking_id"]
        user_id = conflict["user_id"]
        if (user_id, booking_id) in notified_bookings:
            continue
        notified_bookings.add((user_id, booking_id))
        message = (
            f"Your existing booking BK-{booking_id} for {conflict['resource_name']} "
            f"overlaps a confirmed blackout from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}. "
            f"Reason: {reason}. Your booking was not cancelled; contact an administrator for assistance."
        )
        cursor.execute(
            """
            SELECT notification_id FROM notifications
            WHERE user_id = %s AND audience = 'User' AND booking_id = %s AND message = %s
              AND created_at >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)
            LIMIT 1
            """,
            (user_id, booking_id, message),
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO notifications (user_id, booking_id, message, type, audience, is_read)
                VALUES (%s, %s, %s, 'Alert', 'User', 0)
                """,
                (user_id, booking_id, message),
            )


def normalize_selection_times(
    selection: Union[
        BlackoutSelection,
        BlackoutConflictPreview,
        EquipmentBlackoutCreate,
        EquipmentBlackoutConflictPreview,
    ]
) -> Tuple[datetime, datetime]:
    return campus_datetime(selection.start_datetime), campus_datetime(selection.end_datetime)


def expand_weekday_occurrences(
    start_datetime: datetime,
    end_datetime: datetime,
    repeat_weekdays: Sequence[int],
) -> List[Tuple[datetime, datetime]]:
    if not repeat_weekdays:
        return [(start_datetime, end_datetime)]
    if start_datetime.date() > end_datetime.date():
        raise HTTPException(status_code=422, detail="Repeat end date must be on or after the start date.")
    if (end_datetime.date() - start_datetime.date()).days > 365:
        raise HTTPException(status_code=422, detail="Weekly blackouts can be scheduled for up to one year at a time.")
    if end_datetime.time() <= start_datetime.time():
        raise HTTPException(
            status_code=422,
            detail="For weekday repeats, the end time must be later than the start time on each selected day.",
        )

    weekdays = set(repeat_weekdays)
    occurrences = []
    current_date = start_datetime.date()
    while current_date <= end_datetime.date():
        if current_date.weekday() in weekdays:
            occurrences.append((
                datetime.combine(current_date, start_datetime.time()),
                datetime.combine(current_date, end_datetime.time()),
            ))
        current_date += timedelta(days=1)
    if not occurrences:
        raise HTTPException(
            status_code=422,
            detail="The selected weekdays do not occur within the blackout date range.",
        )
    return occurrences


def store_category_ids(category_ids: Sequence[int]) -> Optional[str]:
    return json.dumps(sorted(set(category_ids))) if category_ids else None


def store_resource_ids(resource_ids: Sequence[int]) -> Optional[str]:
    return json.dumps(sorted(set(resource_ids))) if resource_ids else None
