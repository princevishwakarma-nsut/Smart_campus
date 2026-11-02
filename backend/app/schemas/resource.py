from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ResourceFeatureBase(BaseModel):
    feature_name: str = Field(..., max_length=100)
    description: Optional[str] = None


class ResourceFeatureCreate(ResourceFeatureBase):
    pass


class ResourceFeatureResponse(ResourceFeatureBase):
    feature_id: int
    resource_id: int

    class Config:
        from_attributes = True


class ResourceBase(BaseModel):
    category_id: int
    resource_name: str = Field(..., min_length=1, max_length=150)
    resource_code: str = Field(..., min_length=1, max_length=50)
    location: str = Field(..., min_length=1, max_length=200)
    operating_hours: Optional[str] = Field(None, max_length=255)
    capacity: Optional[int] = Field(None, ge=1)
    status: Optional[str] = Field("Available", description="Available, Maintenance, Inactive")
    description: Optional[str] = None


class ResourceCreate(ResourceBase):
    features: Optional[List[str]] = None


class ResourceUpdate(BaseModel):
    category_id: Optional[int] = None
    resource_name: Optional[str] = Field(None, max_length=150)
    resource_code: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = None
    operating_hours: Optional[str] = Field(None, max_length=255)
    capacity: Optional[int] = None
    status: Optional[str] = None
    description: Optional[str] = None
    features: Optional[List[str]] = None


class ResourceStatusUpdate(BaseModel):
    status: str = Field(..., description="Available, Maintenance, Inactive")


class ResourceResponse(ResourceBase):
    resource_id: int
    category_name: Optional[str] = None
    features: List[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
