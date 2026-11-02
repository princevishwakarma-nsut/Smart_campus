from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class DepartmentBase(BaseModel):
    department_name: str = Field(..., max_length=100)
    description: Optional[str] = None
    hod_user_id: Optional[int] = None
    office_location: Optional[str] = Field(None, max_length=150)
    contact_email: Optional[str] = Field(None, max_length=150)
    contact_phone: Optional[str] = Field(None, max_length=20)
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    department_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    hod_user_id: Optional[int] = None
    office_location: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: Optional[bool] = None


class DepartmentResponse(DepartmentBase):
    department_id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
