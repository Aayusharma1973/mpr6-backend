"""
Pydantic schemas for daily tracking domain.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class TakeMedicineIn(BaseModel):
    medicine_id: str


class TrackingRecord(BaseModel):
    medicine_id: str
    medicine_name: str
    taken_at: datetime


class MedicineStatus(BaseModel):
    medicine_id: str
    medicine_name: str
    scheduled_time: str
    status: str  # "taken", "pending", "missed"
    taken_at: Optional[datetime] = None


class TodayStatusOut(BaseModel):
    date: str
    total_slots: int
    taken_count: int
    pending_count: int
    missed_count: int
    adherence_pct: float
    medicines: List[MedicineStatus]


class DailySummary(BaseModel):
    date: str
    taken_count: int
    total_slots: int
    adherence_pct: float


class DayGrid(BaseModel):
    morning: str    # "taken", "missed", "pending", "none"
    afternoon: str
    evening: str


class WeeklyStatusOut(BaseModel):
    user_id: str
    start_date: str
    end_date: str
    daily_summaries: List[DailySummary]
    grid: List[DayGrid]
    overall_adherence_pct: float
