import logging
from datetime import datetime, timedelta
from app.database.transaction import transaction_scope

logger = logging.getLogger(__name__)


def run_booking_reminders() -> int:
    """
    Checks for upcoming approved bookings starting within the next 2 hours
    and sends a reminder notification with strict idempotency (one reminder per booking per user).
    Returns the count of reminders dispatched.
    """
    now = datetime.now()
    window_end = now + timedelta(hours=2)
    sent_count = 0

    with transaction_scope() as (conn, cursor):
        # Query approved bookings starting within 2 hours
        cursor.execute(
            """
            SELECT DISTINCT b.booking_id, b.user_id, b.purpose, br.start_time, r.resource_name
            FROM bookings b
            JOIN booking_resources br ON b.booking_id = br.booking_id
            JOIN resources r ON br.resource_id = r.resource_id
            WHERE b.status = 'Approved'
              AND br.start_time >= %s
              AND br.start_time <= %s
            """,
            (now, window_end)
        )
        upcoming = cursor.fetchall()

        for bk in upcoming:
            b_id = bk["booking_id"]
            u_id = bk["user_id"]

            # Idempotency check: Has a reminder already been sent for this booking and user?
            cursor.execute(
                """
                SELECT notification_id FROM notifications
                WHERE booking_id = %s AND user_id = %s AND type = 'Reminder'
                LIMIT 1
                FOR UPDATE
                """,
                (b_id, u_id)
            )
            if cursor.fetchone():
                continue

            start_str = bk["start_time"].strftime("%H:%M") if hasattr(bk["start_time"], "strftime") else str(bk["start_time"])
            msg = f"Reminder: Your booking BK-{b_id} for '{bk['resource_name']}' starts at {start_str} today ({bk['purpose']})."

            cursor.execute(
                """
                INSERT INTO notifications (user_id, booking_id, message, type, is_read)
                VALUES (%s, %s, %s, 'Reminder', 0)
                """,
                (u_id, b_id, msg)
            )
            sent_count += 1
            logger.info(f"Dispatched reminder for booking BK-{b_id} to user {u_id}")

    return sent_count
