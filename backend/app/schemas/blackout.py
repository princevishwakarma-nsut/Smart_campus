from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class BlackoutCreate(BaseModel):
    resource_id: int
    start_datetime: str = Field(..., description="ISO 8601 string")
    end_datetime: str = Field(..., description="ISO 8601 string")
    reason: str = Field(..., min_length=3, max_length=255)


class BlackoutResponse(BaseModel):
    blackout_id: int
    resource_id: int
    resource_name: Optional[str] = None
    maintenance_id: Optional[int] = None
    start_datetime: datetime
    end_datetime: datetime
    reason: Optional[str] = None
    created_by: int
    creator_name: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
