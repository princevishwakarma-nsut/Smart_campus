from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.core.permissions import get_current_user, require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.schemas.notification import NotificationResponse, UnreadCountResponse
from app.services.reminder_service import run_booking_reminders

router = APIRouter()


@router.get("", response_model=List[NotificationResponse], summary="Get current user's notifications")
def get_my_notifications(current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    audience = "Admin" if current_user.is_admin() else "User"
    db.execute(
        """
        SELECT notification_id, user_id, booking_id, message, type, is_read, created_at
        FROM notifications
        WHERE user_id = %s AND audience = %s
        ORDER BY created_at DESC, notification_id DESC
        LIMIT 50
        """,
        (current_user.user_id, audience)
    )
    rows = db.fetchall()

    return [
        NotificationResponse(
            notification_id=r["notification_id"],
            user_id=r["user_id"],
            booking_id=r["booking_id"],
            message=r["message"],
            type=r["type"],
            is_read=bool(r["is_read"]),
            created_at=r["created_at"]
        )
        for r in rows
    ]


@router.get("/unread-count", response_model=UnreadCountResponse, summary="Get unread notification count")
def get_unread_count(current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    audience = "Admin" if current_user.is_admin() else "User"
    db.execute(
        "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = %s AND audience = %s AND is_read = 0",
        (current_user.user_id, audience)
    )
    res = db.fetchone()
    return UnreadCountResponse(unread_count=res["cnt"] if res else 0)


@router.patch("/{notification_id}/read", summary="Mark notification as read")
def mark_read(notification_id: int, current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    audience = "Admin" if current_user.is_admin() else "User"
    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE notification_id = %s AND user_id = %s AND audience = %s",
        (notification_id, current_user.user_id, audience)
    )
    return {"message": "Notification marked as read.", "is_read": True}


@router.patch("/read-all", summary="Mark all user notifications as read")
def mark_all_read(current_user: UserContext = Depends(get_current_user), db=Depends(get_db)):
    audience = "Admin" if current_user.is_admin() else "User"
    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = %s AND audience = %s AND is_read = 0",
        (current_user.user_id, audience)
    )
    return {"message": "All notifications marked as read."}


@router.post("/send-reminders", summary="Execute automated booking reminder runner (Admin/Staff/Cron)")
def trigger_reminders(current_user: UserContext = Depends(require_roles(Role.ADMIN, Role.STAFF))):
    count = run_booking_reminders()
    return {"message": f"Reminder runner completed. Dispatched {count} reminders.", "sent_count": count}
