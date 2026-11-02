from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class NotificationResponse(BaseModel):
    notification_id: int
    user_id: int
    booking_id: Optional[int] = None
    message: str
    type: str  # Info, Reminder, Approval, Alert
    is_read: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    unread_count: int
