import re
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class DashboardStatsResponse(BaseModel):
    total_resources: int
    available_resources: int
    maintenance_resources: int
    total_bookings: int
    pending_approvals: int
    approved_bookings: int
    rejected_bookings: int
    cancelled_bookings: int
    active_users: int
    total_societies: int
    upcoming_bookings: List[Dict[str, Any]] = []
    category_distribution: List[Dict[str, Any]] = []
    equipment_types: int = 0
    equipment_units: int = 0
    maintenance_tickets: int = 0
    bookings_today: int = 0
    recent_activity: List[Dict[str, Any]] = []


class UtilizationReportResponse(BaseModel):
    total_hours_booked: float
    busiest_resources: List[Dict[str, Any]] = []
    peak_hours: List[Dict[str, Any]] = []
    status_breakdown: Dict[str, int] = {}


class SystemSettingsUpdate(BaseModel):
    academic_year: str = Field(min_length=9, max_length=9)
    timetable_enforcement: bool
    booking_window_days: int = Field(ge=1, le=365)
    approval_mode: Literal["Manual", "ByCategory"]
    approval_categories: List[str] = Field(default_factory=list)
    min_booking_minutes: int = Field(ge=15, le=1440)
    max_booking_minutes: int = Field(ge=15, le=1440)
    cancellation_cutoff_hours: int = Field(ge=0, le=720)

    @field_validator("academic_year")
    @classmethod
    def validate_academic_year(cls, value):
        if not re.fullmatch(r"\d{4}-\d{4}", value):
            raise ValueError("Academic year must use the YYYY-YYYY format.")
        return value
