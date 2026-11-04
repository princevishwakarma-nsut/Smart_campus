from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


BlackoutReasonCategory = Literal[
    "Maintenance",
    "University Examination",
    "College Event",
    "Holiday",
    "Cleaning",
    "Renovation",
    "Official Function",
    "Safety Restriction",
    "Other",
]


class BlackoutSelection(BaseModel):
    resource_id: Optional[int] = Field(None, ge=1)
    resource_ids: List[int] = Field(default_factory=list, max_length=1000)
    excluded_resource_ids: List[int] = Field(default_factory=list, max_length=1000)
    category_ids: List[int] = Field(default_factory=list, max_length=100)
    start_datetime: datetime
    end_datetime: datetime
    reason_category: BlackoutReasonCategory = "Other"
    reason_explanation: Optional[str] = Field(None, max_length=2000)
    reason: Optional[str] = Field(None, min_length=3, max_length=255)
    repeat_weekdays: List[int] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def validate_blackout(self):
        if self.end_datetime <= self.start_datetime:
            raise ValueError("End datetime must be after start datetime.")
        if not (self.resource_ids or self.resource_id or self.category_ids):
            raise ValueError("Select at least one resource or resource category.")
        explanation = (self.reason_explanation or self.reason or "").strip()
        if not explanation:
            raise ValueError("Reason for unavailability is required.")
        self.reason_explanation = explanation
        self.reason = explanation[:255]
        self.resource_ids = sorted(set(self.resource_ids + ([self.resource_id] if self.resource_id else [])))
        self.excluded_resource_ids = sorted(set(self.excluded_resource_ids))
        self.category_ids = sorted(set(self.category_ids))
        if any(day < 0 or day > 6 for day in self.repeat_weekdays):
            raise ValueError("Repeat weekdays must use values from 0 (Monday) to 6 (Sunday).")
        self.repeat_weekdays = sorted(set(self.repeat_weekdays))
        return self


class BlackoutCreate(BlackoutSelection):
    confirm_booking_conflicts: bool = False


class BlackoutConflictPreview(BaseModel):
    resource_id: Optional[int] = Field(None, ge=1)
    resource_ids: List[int] = Field(default_factory=list, max_length=1000)
    excluded_resource_ids: List[int] = Field(default_factory=list, max_length=1000)
    category_ids: List[int] = Field(default_factory=list, max_length=100)
    start_datetime: datetime
    end_datetime: datetime
    repeat_weekdays: List[int] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.end_datetime <= self.start_datetime:
            raise ValueError("End datetime must be after start datetime.")
        if not (self.resource_ids or self.resource_id or self.category_ids):
            raise ValueError("Select at least one resource or resource category.")
        self.resource_ids = sorted(set(self.resource_ids + ([self.resource_id] if self.resource_id else [])))
        self.excluded_resource_ids = sorted(set(self.excluded_resource_ids))
        self.category_ids = sorted(set(self.category_ids))
        if any(day < 0 or day > 6 for day in self.repeat_weekdays):
            raise ValueError("Repeat weekdays must use values from 0 (Monday) to 6 (Sunday).")
        self.repeat_weekdays = sorted(set(self.repeat_weekdays))
        return self


class EquipmentBlackoutSelection(BaseModel):
    equipment_ids: List[int] = Field(..., min_length=1, max_length=1000)
    start_datetime: datetime
    end_datetime: datetime
    reason_category: BlackoutReasonCategory = "Other"
    reason_explanation: Optional[str] = Field(None, max_length=2000)
    repeat_weekdays: List[int] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def validate_equipment_blackout(self):
        if self.end_datetime <= self.start_datetime:
            raise ValueError("End datetime must be after start datetime.")
        if any(day < 0 or day > 6 for day in self.repeat_weekdays):
            raise ValueError("Repeat weekdays must use values from 0 (Monday) to 6 (Sunday).")
        explanation = (self.reason_explanation or "").strip()
        if not explanation:
            raise ValueError("Reason for unavailability is required.")
        self.reason_explanation = explanation
        self.equipment_ids = sorted(set(self.equipment_ids))
        self.repeat_weekdays = sorted(set(self.repeat_weekdays))
        return self


class EquipmentBlackoutCreate(EquipmentBlackoutSelection):
    confirm_booking_conflicts: bool = False


class EquipmentBlackoutConflictPreview(BaseModel):
    equipment_ids: List[int] = Field(..., min_length=1, max_length=1000)
    start_datetime: datetime
    end_datetime: datetime
    repeat_weekdays: List[int] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def validate_equipment_preview(self):
        if self.end_datetime <= self.start_datetime:
            raise ValueError("End datetime must be after start datetime.")
        if any(day < 0 or day > 6 for day in self.repeat_weekdays):
            raise ValueError("Repeat weekdays must use values from 0 (Monday) to 6 (Sunday).")
        self.equipment_ids = sorted(set(self.equipment_ids))
        self.repeat_weekdays = sorted(set(self.repeat_weekdays))
        return self


class EquipmentBlackoutResponse(BaseModel):
    equipment_blackout_id: int
    item_id: int
    item_name: str
    category: Optional[str] = None
    blackout_group_id: str
    start_datetime: datetime
    end_datetime: datetime
    reason_category: str = "Other"
    reason_explanation: str
    status: str = "Active"
    window_state: str = "Upcoming"
    created_by: int
    creator_name: Optional[str] = None
    created_at: Optional[datetime] = None


class BlackoutResponse(BaseModel):
    blackout_id: int
    resource_id: int
    resource_name: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    maintenance_id: Optional[int] = None
    start_datetime: datetime
    end_datetime: datetime
    reason: Optional[str] = None
    reason_category: str = "Other"
    reason_explanation: Optional[str] = None
    blackout_group_id: Optional[str] = None
    category_ids: List[int] = Field(default_factory=list)
    excluded_resource_ids: List[int] = Field(default_factory=list)
    status: str = "Active"
    window_state: str = "Upcoming"
    created_by: int
    creator_name: Optional[str] = None
    cancelled_by: Optional[int] = None
    cancelled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
