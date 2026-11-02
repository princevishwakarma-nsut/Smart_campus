from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserCreateAdmin(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: str = Field(..., description="Faculty, Staff, Student, Admin")
    department_id: Optional[int] = None
    phone_no: Optional[str] = Field(None, max_length=20)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    department_id: Optional[int] = None
    phone_no: Optional[str] = Field(None, max_length=20)
    role: Optional[str] = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, description="New password for user (minimum 8 characters)")
