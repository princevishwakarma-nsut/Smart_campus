from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class MaintenanceCreate(BaseModel):
    resource_id: Optional[int] = None
    item_id: Optional[int] = None
    issue_description: str = Field(..., min_length=3)
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    remarks: Optional[str] = None


class MaintenanceComplete(BaseModel):
    remarks: Optional[str] = "Maintenance completed successfully"


class MaintenanceResponse(BaseModel):
    maintenance_id: int
    resource_id: Optional[int] = None
    resource_name: Optional[str] = None
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    reported_by: int
    reporter_name: Optional[str] = None
    assigned_to: Optional[int] = None
    issue_description: str
    status: str
    reported_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    remarks: Optional[str] = None

    class Config:
        from_attributes = True
