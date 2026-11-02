from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    department_id: Optional[int] = None
    phone_no: Optional[str] = Field(None, max_length=20)
    role: Optional[str] = Field("Student", description="Student, Faculty, Staff (Admin cannot self-register)")


class UserResponse(BaseModel):
    user_id: int
    name: str
    email: str
    role: str
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    phone_no: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")


class RegisterFacultyRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    department_id: Optional[int] = None
    phone_no: Optional[str] = Field(None, max_length=20)
    employee_id: str = Field(..., min_length=1, max_length=50, description="Staff or Employee ID")
    designation: Optional[str] = Field(None, max_length=100)


class RegisterSocietyRequest(BaseModel):
    club_name: str = Field(..., min_length=2, max_length=100)
    department_id: Optional[int] = None
    description: Optional[str] = None
    established_year: Optional[int] = None
    coordinator_email: EmailStr = Field(..., description="Email of existing registered Student or Faculty coordinator")


class FacultyRequestResponse(BaseModel):
    request_id: int
    name: str
    email: str
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    phone_no: Optional[str] = None
    employee_id: str
    designation: Optional[str] = None
    status: str
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ReviewActionRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=255)

