from typing import Optional, List
from datetime import date, time
from pydantic import BaseModel, Field


class TimetableResponse(BaseModel):
    timetable_id: int
    resource_id: int
    resource_name: Optional[str] = None
    department_name: Optional[str] = None
    section: Optional[str] = None
    subject_name: Optional[str] = None
    day_of_week: str
    start_time: str
    end_time: str
    academic_year: Optional[str] = None
    semester: Optional[str] = None
    class_type: Optional[str] = None
    assigned_faculty: Optional[List[dict]] = None

    class Config:
        from_attributes = True


class AssignFacultyRequest(BaseModel):
    faculty_user_ids: Optional[List[int]] = Field(None, description="List of active Faculty user IDs to assign")
    faculty_user_id: Optional[int] = Field(None, description="Single active Faculty user ID to assign")


class FacultyUserOption(BaseModel):
    user_id: int
    name: str
    email: str
    department_name: Optional[str] = None
    is_active: bool


class AvailabilitySlotCheck(BaseModel):
    resource_id: int
    start_time: str
    end_time: str


class AvailabilityResponse(BaseModel):
    is_available: bool
    state: str  # 'free', 'taken', 'blocked', 'maintenance', 'timetable_conflict'
    reason: Optional[str] = None
    conflicting_booking: Optional[dict] = None
    conflicting_timetable: Optional[dict] = None
