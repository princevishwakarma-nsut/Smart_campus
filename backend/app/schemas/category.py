from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class CategoryBase(BaseModel):
    category_name: str = Field(..., max_length=100)
    description: Optional[str] = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    category_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class CategoryResponse(CategoryBase):
    category_id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
