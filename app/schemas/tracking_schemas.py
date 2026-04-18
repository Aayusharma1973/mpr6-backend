"""
Pydantic schemas for daily tracking domain.
"""
from datetime import datetime
from pydantic import BaseModel


class TakeMedicineIn(BaseModel):
    medicine_id: str
    date: str  # YYYY-MM-DD  (defaults to today on backend if omitted)


class TrackingRecordOut(BaseModel):
    id: int
    user_id: str
    medicine_id: str
    date: str
    taken: bool
    timestamp: datetime

    model_config = {"from_attributes": True}


class TodayStatusOut(BaseModel):
    date: str
    total: int
    taken: int
    pending: int
    adherence_pct: float
    records: list[TrackingRecordOut]
    synced_to_mongo: bool
