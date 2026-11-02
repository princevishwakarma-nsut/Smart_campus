from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class SocietyCreate(BaseModel):
    club_name: str = Field(..., max_length=100)
    department_id: Optional[int] = None
    description: Optional[str] = None
    faculty_coordinator_id: Optional[int] = None
    established_year: Optional[int] = None


class SocietyUpdate(BaseModel):
    club_name: Optional[str] = Field(None, max_length=100)
    department_id: Optional[int] = None
    description: Optional[str] = None
    faculty_coordinator_id: Optional[int] = None
    established_year: Optional[int] = None
    is_active: Optional[bool] = None


class SocietyMemberAdd(BaseModel):
    user_id: int
    member_role: Optional[str] = Field("Member", description="President, Vice President, Secretary, Treasurer, Coordinator, Member")
    can_manage: Optional[bool] = False
    can_book: Optional[bool] = True


class SocietyMemberResponse(BaseModel):
    club_member_id: int
    club_id: int
    user_id: int
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    member_role: str
    can_manage: bool
    can_book: bool
    is_active: bool
    joined_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SocietyResponse(BaseModel):
    club_id: int
    club_name: str
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    description: Optional[str] = None
    faculty_coordinator_id: Optional[int] = None
    faculty_coordinator_name: Optional[str] = None
    created_by: Optional[int] = None
    established_year: Optional[int] = None
    is_active: bool
    status: Optional[str] = "Approved"
    rejection_reason: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    members_count: Optional[int] = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
