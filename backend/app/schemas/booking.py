from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class BookingResourceRequest(BaseModel):
    resource_id: int
    start_time: str
    end_time: str


class BookingParticipantRequest(BaseModel):
    user_id: int
    participant_role: Optional[str] = "Participant"  # Organizer, Participant, Volunteer


class BookingEquipmentRequest(BaseModel):
    item_id: int
    quantity: int = Field(1, ge=1, description="Quantity of equipment units requested")


class BookingCreate(BaseModel):
    resource_id: Optional[int] = None  # single resource shortcut
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    start_datetime: Optional[str] = None  # alias for start_time
    end_datetime: Optional[str] = None    # alias for end_time
    resources: Optional[List[BookingResourceRequest]] = None  # multi-resource
    purpose: str = Field(..., min_length=3, max_length=255)
    expected_participants: Optional[int] = Field(1, ge=1)
    society_id: Optional[int] = None
    participants: Optional[List[BookingParticipantRequest]] = None
    equipment_requests: Optional[List[BookingEquipmentRequest]] = None
    equipment_ids: Optional[List[int]] = None  # legacy single-item list compatibility


class BookingCancelRequest(BaseModel):
    remarks: Optional[str] = "Cancelled by user"


class BookingResourceResponse(BaseModel):
    booking_resource_id: int
    resource_id: int
    resource_name: Optional[str] = None
    resource_code: Optional[str] = None
    location: Optional[str] = None
    start_time: str
    end_time: str
    status: str


class BookingEquipmentResponse(BaseModel):
    booking_equipment_id: Optional[int] = None
    item_id: int
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = "Piece"
    requested_quantity: int
    approved_quantity: int = 0
    issued_quantity: int = 0
    returned_good_quantity: int = 0
    returned_damaged_quantity: int = 0
    lost_quantity: int = 0
    location: Optional[str] = "Gym"


class BookingResponse(BaseModel):
    booking_id: int
    user_id: int
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    society_id: Optional[int] = None
    society_name: Optional[str] = None
    purpose: str
    expected_participants: int
    status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    resources: List[BookingResourceResponse] = []
    equipment: List[BookingEquipmentResponse] = []
    decided_by: Optional[str] = None
    remarks: Optional[str] = None

    class Config:
        from_attributes = True
