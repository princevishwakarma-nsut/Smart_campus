from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ApprovalAction(BaseModel):
    remarks: Optional[str] = Field("", max_length=500)


class ApprovalResponse(BaseModel):
    approval_id: int
    booking_id: int
    booking_resource_id: Optional[int] = None
    approver_id: int
    approver_name: Optional[str] = None
    decision: str
    remarks: Optional[str] = None
    decided_at: Optional[datetime] = None

    class Config:
        from_attributes = True
