from datetime import datetime
from typing import Dict, List, Sequence


def find_equipment_booking_conflicts(
    cursor,
    item_ids: Sequence[int],
    start_datetime: datetime,
    end_datetime: datetime,
    locking_read: bool = False,
) -> List[Dict]:
    item_ids = sorted(set(item_ids))
    if not item_ids:
        return []
    query = f"""
        SELECT bei.booking_id, bei.item_id, ei.item_name, b.user_id,
               u.name AS requester_name, b.start_time, b.end_time,
               b.status AS booking_status, b.purpose, bei.requested_quantity
        FROM booking_equipment_items bei
        JOIN bookings b ON b.booking_id = bei.booking_id
        JOIN users u ON u.user_id = b.user_id
        JOIN equipment_items ei ON ei.item_id = bei.item_id
        WHERE bei.item_id IN ({','.join(['%s'] * len(item_ids))})
          AND b.status IN ('Pending', 'Approved')
          AND b.start_time < %s
          AND b.end_time > %s
        ORDER BY ei.item_name, b.start_time, bei.booking_id
    """
    if locking_read:
        query += " FOR UPDATE"
    cursor.execute(query, (*item_ids, end_datetime, start_datetime))
    return cursor.fetchall()


def notify_admins_of_equipment_blackout_conflicts(
    cursor,
    actor_id: int,
    conflicts: List[Dict],
    start_datetime: datetime,
    end_datetime: datetime,
) -> None:
    if not conflicts:
        return
    cursor.execute(
        "SELECT user_id FROM users WHERE role = 'Admin' AND is_active = 1 AND user_id != %s",
        (actor_id,),
    )
    admins = cursor.fetchall()
    for conflict in conflicts:
        message = (
            f"Equipment blackout conflict: {conflict['item_name']} requested by "
            f"{conflict['requester_name']} has booking BK-{conflict['booking_id']} "
            f"from {conflict['start_time']:%Y-%m-%d %H:%M} to {conflict['end_time']:%Y-%m-%d %H:%M}. "
            f"Proposed blackout: {start_datetime:%Y-%m-%d %H:%M} to {end_datetime:%Y-%m-%d %H:%M}."
        )
        for admin in admins:
            cursor.execute(
                """
                SELECT notification_id FROM notifications
                WHERE user_id = %s AND audience = 'Admin' AND booking_id = %s AND message = %s
                  AND created_at >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)
                LIMIT 1
                """,
                (admin["user_id"], conflict["booking_id"], message),
            )
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO notifications (user_id, booking_id, message, type, audience, is_read)
                    VALUES (%s, %s, %s, 'Alert', 'Admin', 0)
                    """,
                    (admin["user_id"], conflict["booking_id"], message),
                )


def notify_users_of_confirmed_equipment_blackout_conflicts(
    cursor,
    conflicts: List[Dict],
    start_datetime: datetime,
    end_datetime: datetime,
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
            f"Your existing booking BK-{booking_id} for {conflict['item_name']} overlaps an equipment "
            f"blackout from {start_datetime:%Y-%m-%d %H:%M} to {end_datetime:%Y-%m-%d %H:%M}. "
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
