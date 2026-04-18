"""
Pydantic schemas for Medicine domain.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TimeSlot(BaseModel):
    time: str = Field(..., example="08:00 AM")
    instructions: Optional[str] = None


# ── Request schemas ───────────────────────────────────────────────────────────

class MedicineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    dosage: str = Field(..., example="500mg")
    frequency: str = Field(..., example="2x Daily")
    time_slots: list[TimeSlot] = Field(default_factory=list)
    instructions: Optional[str] = None
    duration_days: Optional[int] = None  # None = ongoing


class MedicineUpdate(BaseModel):
    name: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    time_slots: Optional[list[TimeSlot]] = None
    instructions: Optional[str] = None
    duration_days: Optional[int] = None


# ── Response schemas ──────────────────────────────────────────────────────────

class MedicineOut(BaseModel):
    id: str
    user_id: str
    name: str
    dosage: str
    frequency: str
    time_slots: list[TimeSlot]
    instructions: Optional[str]
    duration_days: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}
