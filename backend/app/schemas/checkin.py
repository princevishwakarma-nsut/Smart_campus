from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class CheckinCreate(BaseModel):
    booking_participant_id: int
    remarks: Optional[str] = None


class CheckoutRequest(BaseModel):
    remarks: Optional[str] = None


class NoShowRequest(BaseModel):
    remarks: Optional[str] = "Marked as no-show"


class CheckinResponse(BaseModel):
    checkin_id: int
    booking_participant_id: int
    booking_id: Optional[int] = None
    user_name: Optional[str] = None
    verified_by: Optional[int] = None
    verifier_name: Optional[str] = None
    checkin_time: Optional[datetime] = None
    checkout_time: Optional[datetime] = None
    status: str
    remarks: Optional[str] = None

    class Config:
        from_attributes = True
