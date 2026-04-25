"""
Business logic for daily medicine tracking.
  - Directly stores tracking events in MongoDB (daily_logs collection)
"""
from datetime import datetime, timezone, date as dt_date, timedelta
from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from app.database.mongo import medicines_col, daily_logs_col
from app.schemas.tracking_schemas import (
    TakeMedicineIn, 
    TodayStatusOut, 
    MedicineStatus, 
    WeeklyStatusOut, 
    DailySummary,
    DayGrid
)
from app.utils.mongo_helpers import str_to_oid
from loguru import logger


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_time(time_str: str) -> datetime:
    """Parses '08:00 AM' into a dummy datetime for comparison."""
    return datetime.strptime(time_str, "%I:%M %p")

async def get_daily_log(user_id: str, date_str: str) -> Dict[str, Any]:
    col = daily_logs_col()
    log = await col.find_one({"user_id": user_id, "date": date_str})
    if not log:
        return {"user_id": user_id, "date": date_str, "medicines_taken": []}
    return log

async def get_user_medicines(user_id: str) -> List[Dict[str, Any]]:
    col = medicines_col()
    cursor = col.find({"user_id": user_id})
    return await cursor.to_list(length=200)

def get_period_status(statuses: List[MedicineStatus]) -> str:
    """
    Calculates the aggregate status for a time period (morning/afternoon/evening).
    Rules:
    - "none": No medications scheduled.
    - "missed": Any medication is "missed".
    - "pending": Any medication is "pending" (and none are missed).
    - "taken": All medications are "taken".
    """
    if not statuses:
        return "none"
    
    if any(s.status == "missed" for s in statuses):
        return "missed"
    
    if any(s.status == "pending" for s in statuses):
        return "pending"
    
    return "taken"

async def calculate_daily_status(user_id: str, target_date: dt_date) -> TodayStatusOut:
    date_str = target_date.isoformat()
    medicines = await get_user_medicines(user_id)
    log = await get_daily_log(user_id, date_str)
    
    intakes = log.get("medicines_taken", [])
    is_today = target_date == dt_date.today()
    is_past = target_date < dt_date.today()
    
    medicine_statuses = []
    
    for med in medicines:
        med_id = str(med["_id"])
        med_name = med["name"]
        time_slots = med.get("time_slots", [])
        
        sorted_slots = sorted(time_slots, key=lambda x: parse_time(x["time"]))
        
        med_intakes = [i for i in intakes if i["medicine_id"] == med_id]
        med_intakes.sort(key=lambda x: x["taken_at"])
        
        intake_ptr = 0
        for slot in sorted_slots:
            scheduled_time_str = slot["time"]
            status = "pending"
            taken_at = None
            
            if intake_ptr < len(med_intakes):
                intake_data = med_intakes[intake_ptr]
                status = "taken"
                taken_at = intake_data["taken_at"]
                intake_ptr += 1
            else:
                if is_past:
                    status = "missed"
                elif is_today:
                    slot_time = parse_time(scheduled_time_str).time()
                    local_now = datetime.now()
                    slot_dt = datetime.combine(dt_date.today(), slot_time)
                    if slot_dt < local_now:
                        status = "missed"
                    else:
                        status = "pending"
                else:
                    status = "pending"
            
            medicine_statuses.append(MedicineStatus(
                medicine_id=med_id,
                medicine_name=med_name,
                scheduled_time=scheduled_time_str,
                status=status,
                taken_at=taken_at
            ))

    total_slots = len(medicine_statuses)
    taken_count = sum(1 for s in medicine_statuses if s.status == "taken")
    pending_count = sum(1 for s in medicine_statuses if s.status == "pending")
    missed_count = sum(1 for s in medicine_statuses if s.status == "missed")
    
    adherence_pct = (taken_count / total_slots * 100) if total_slots > 0 else 0.0
    
    return TodayStatusOut(
        date=date_str,
        total_slots=total_slots,
        taken_count=taken_count,
        pending_count=pending_count,
        missed_count=missed_count,
        adherence_pct=round(adherence_pct, 1),
        medicines=medicine_statuses
    )


# ── Public service functions ──────────────────────────────────────────────────

async def mark_taken(user_id: str, data: TakeMedicineIn) -> Dict[str, Any]:
    date_str = dt_date.today().isoformat()
    col = daily_logs_col()
    
    med_col = medicines_col()
    med = await med_col.find_one({"_id": str_to_oid(data.medicine_id), "user_id": user_id})
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")
    
    new_record = {
        "medicine_id": data.medicine_id,
        "medicine_name": med["name"],
        "taken_at": datetime.now(timezone.utc)
    }
    
    await col.update_one(
        {"user_id": user_id, "date": date_str},
        {"$push": {"medicines_taken": new_record}},
        upsert=True
    )
    return new_record


async def get_today_status(user_id: str) -> TodayStatusOut:
    return await calculate_daily_status(user_id, dt_date.today())


async def get_weekly_status(user_id: str) -> WeeklyStatusOut:
    today = dt_date.today()
    start_date = today - timedelta(days=6)
    
    daily_summaries = []
    grid = []
    total_taken = 0
    total_slots = 0
    
    for i in range(7):
        target_date = start_date + timedelta(days=i)
        status_out = await calculate_daily_status(user_id, target_date)
        
        daily_summaries.append(DailySummary(
            date=status_out.date,
            taken_count=status_out.taken_count,
            total_slots=status_out.total_slots,
            adherence_pct=status_out.adherence_pct
        ))
        
        # Calculate Grid for this day
        morning_meds = []
        afternoon_meds = []
        evening_meds = []
        
        for m in status_out.medicines:
            hour = parse_time(m.scheduled_time).hour
            if 0 <= hour < 12:
                morning_meds.append(m)
            elif 12 <= hour < 17:
                afternoon_meds.append(m)
            else:
                evening_meds.append(m)
        
        grid.append(DayGrid(
            morning=get_period_status(morning_meds),
            afternoon=get_period_status(afternoon_meds),
            evening=get_period_status(evening_meds)
        ))
        
        total_taken += status_out.taken_count
        total_slots += status_out.total_slots
        
    overall_adherence = (total_taken / total_slots * 100) if total_slots > 0 else 0.0
    
    return WeeklyStatusOut(
        user_id=user_id,
        start_date=start_date.isoformat(),
        end_date=today.isoformat(),
        daily_summaries=daily_summaries,
        grid=grid,
        overall_adherence_pct=round(overall_adherence, 1)
    )
