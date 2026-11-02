from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel, Field


class EquipmentCreate(BaseModel):
    item_name: str = Field(..., min_length=2, max_length=150)
    item_code: Optional[str] = Field(None, max_length=50)
    serial_no: Optional[str] = None
    category: str = Field("Other", description="Sports, Electronics, Audio/Visual, IT, Accessories, Other")
    condition_status: Optional[str] = None
    availability_status: Optional[str] = None
    description: Optional[str] = None
    unit: str = Field("Piece", max_length=50)
    total_quantity: int = Field(1, ge=1)
    location: str = Field("Gym", max_length=100)
    purchase_date: Optional[date] = None

    def get_code(self) -> str:
        code = (self.item_code or "").strip() or (self.serial_no or "").strip()
        if not code:
            import uuid
            return f"EQ-{uuid.uuid4().hex[:8].upper()}"
        return code


class EquipmentUpdate(BaseModel):
    item_name: Optional[str] = Field(None, min_length=2, max_length=150)
    serial_no: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None
    location: Optional[str] = None
    purchase_date: Optional[date] = None
    is_active: Optional[bool] = None


class EquipmentStatusUpdate(BaseModel):
    is_active: bool


class EquipmentStockAdjustRequest(BaseModel):
    action: Optional[str] = Field(None, description="add, damage, maintenance, repair, lost, recover")
    adjustment_type: Optional[str] = None
    quantity: int = Field(..., ge=1)
    notes: Optional[str] = None

    def get_action(self) -> str:
        act = self.action or self.adjustment_type
        if not act:
            raise ValueError("action or adjustment_type required")
        return act.strip().lower()


class EquipmentIssueQuantityRequest(BaseModel):
    booking_id: int
    quantity: Optional[int] = Field(1, ge=1)
    notes: Optional[str] = None


class EquipmentReturnQuantityRequest(BaseModel):
    booking_id: Optional[int] = None
    returned_good_quantity: Optional[int] = 0
    good_quantity: Optional[int] = None
    returned_damaged_quantity: Optional[int] = 0
    damaged_quantity: Optional[int] = None
    lost_quantity: int = Field(0, ge=0)
    condition_on_return: Optional[str] = None
    remarks: Optional[str] = None
    notes: Optional[str] = None

    def get_good(self) -> int:
        if self.condition_on_return and self.condition_on_return.lower() != "good":
            return 0
        return self.good_quantity if self.good_quantity is not None else (self.returned_good_quantity or 0)

    def get_damaged(self) -> int:
        if self.condition_on_return and self.condition_on_return.lower() == "damaged":
            return 1
        return self.damaged_quantity if self.damaged_quantity is not None else (self.returned_damaged_quantity or 0)


class EquipmentResponse(BaseModel):
    item_id: int
    item_code: str
    item_name: str
    serial_no: Optional[str] = None
    category: str
    description: Optional[str] = None
    unit: str = "Piece"
    total_quantity: int
    damaged_quantity: int = 0
    maintenance_quantity: int = 0
    lost_quantity: int = 0
    usable_quantity: Optional[int] = 0
    reserved_quantity: Optional[int] = 0
    available_quantity: Optional[int] = 0
    overdue_issued_quantity: Optional[int] = 0
    location: str = "Gym"
    purchase_date: Optional[date] = None
    condition_status: Optional[str] = "Good"
    availability_status: Optional[str] = "Available"
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EquipmentStockMovementResponse(BaseModel):
    movement_id: int
    item_id: int
    item_name: Optional[str] = None
    movement_type: str
    quantity: int
    booking_id: Optional[int] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    created_at: Optional[datetime] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class EquipmentSummaryResponse(BaseModel):
    total_types: int
    total_units: int
    available_units: int
    reserved_units: int
    damaged_units: int
    maintenance_units: int
    lost_units: int
    categories: List[dict] = []
