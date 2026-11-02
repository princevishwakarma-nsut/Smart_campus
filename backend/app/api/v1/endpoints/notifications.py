from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.permissions import get_current_user, require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.schemas.notification import NotificationResponse, UnreadCountResponse
from app.services.reminder_service import run_booking_reminders

router = APIRouter()


@router.get("", response_model=List[NotificationResponse], summary="Get current user's notifications")
def get_my_notifications(
    is_read: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    before_id: Optional[int] = Query(None, ge=1),
    current_user: UserContext = Depends(get_current_user),
    db=Depends(get_db)
):
    audience = "Admin" if current_user.is_admin() else "User"
    read_filter = ""
    params = [current_user.user_id, audience]
    if is_read is not None:
        read_filter = " AND n.is_read = %s"
        params.append(1 if is_read else 0)
    before_filter = ""
    if before_id is not None:
        before_filter = " AND n.notification_id < %s"
        params.append(before_id)
    db.execute(
        f"""
        SELECT n.notification_id, n.user_id, n.booking_id, n.message, n.type,
               n.is_read, n.created_at, requester.name AS requester_name,
               (SELECT GROUP_CONCAT(DISTINCT r.resource_name ORDER BY r.resource_name SEPARATOR ', ')
                FROM booking_resources br JOIN resources r ON r.resource_id = br.resource_id
                WHERE br.booking_id = n.booking_id) AS resource_name,
               (SELECT GROUP_CONCAT(DISTINCT ei.item_name ORDER BY ei.item_name SEPARATOR ', ')
                FROM booking_equipment_items bei JOIN equipment_items ei ON ei.item_id = bei.item_id
                WHERE bei.booking_id = n.booking_id) AS equipment_name,
               b.start_time, b.end_time
        FROM notifications n
        LEFT JOIN bookings b ON b.booking_id = n.booking_id
        LEFT JOIN users requester ON requester.user_id = b.user_id
        WHERE n.user_id = %s AND n.audience = %s{read_filter}{before_filter}
        ORDER BY n.created_at DESC, n.notification_id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset])
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
            created_at=r["created_at"],
            requester_name=r["requester_name"],
            resource_name=r["resource_name"],
            equipment_name=r["equipment_name"],
            start_time=r["start_time"],
            end_time=r["end_time"]
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
        "UPDATE notifications SET is_read = 1 WHERE notification_id = %s AND user_id = %s AND audience = %s AND is_read = 0",
        (notification_id, current_user.user_id, audience)
    )
    if db.rowcount == 0:
        db.execute(
            "SELECT notification_id FROM notifications WHERE notification_id = %s AND user_id = %s AND audience = %s",
            (notification_id, current_user.user_id, audience)
        )
        if not db.fetchone():
            raise HTTPException(status_code=404, detail="Notification not found.")
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
