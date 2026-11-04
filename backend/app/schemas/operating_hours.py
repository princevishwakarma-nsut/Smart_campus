from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class OperatingHoursBulkUpdate(BaseModel):
    resource_ids: List[int] = Field(default_factory=list)
    category_ids: List[int] = Field(default_factory=list)
    all_resources: bool = False
    is_active: bool = True
    weekdays: List[str] = Field(default_factory=list)
    closed_days: List[str] = Field(default_factory=list)
    open_time: Optional[time] = None
    close_time: Optional[time] = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if not (self.all_resources or self.resource_ids or self.category_ids):
            raise ValueError("Select resources, categories, or all resources.")
        if len(set(self.weekdays)) != len(self.weekdays) or len(set(self.closed_days)) != len(self.closed_days):
            raise ValueError("Weekdays and closed days must not contain duplicates.")
        if set(self.weekdays) - set(WEEKDAYS) or set(self.closed_days) - set(WEEKDAYS):
            raise ValueError("Select valid weekdays.")
        if set(self.weekdays) & set(self.closed_days):
            raise ValueError("A weekday cannot be both open and closed.")
        if not self.weekdays and not self.closed_days:
            raise ValueError("Select at least one open or closed weekday.")
        if self.weekdays:
            if self.open_time is None or self.close_time is None:
                raise ValueError("Opening and closing times are required for open weekdays.")
            if self.open_time == self.close_time:
                raise ValueError("Opening and closing times must differ.")
        return self


class OperatingHoursExceptionCreate(BaseModel):
    resource_ids: List[int] = Field(default_factory=list)
    category_ids: List[int] = Field(default_factory=list)
    all_resources: bool = False
    start_date: date
    end_date: date
    is_closed: bool = True
    open_time: Optional[time] = None
    close_time: Optional[time] = None
    reason: str = Field(..., min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_exception(self):
        if not (self.all_resources or self.resource_ids or self.category_ids):
            raise ValueError("Select resources, categories, or all resources.")
        if self.end_date < self.start_date:
            raise ValueError("Exception end date must be on or after its start date.")
        if not self.is_closed:
            if self.open_time is None or self.close_time is None:
                raise ValueError("Opening and closing times are required for an open-hours exception.")
            if self.open_time == self.close_time:
                raise ValueError("Opening and closing times must differ.")
        return self
