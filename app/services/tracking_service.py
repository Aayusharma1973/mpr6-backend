"""
Business logic for daily medicine tracking.
  - Tracks dose-taken events in SQLite
  - Syncs completed days to MongoDB (daily_logs collection)
"""
from datetime import datetime, timezone, date as dt_date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.sqlite_models import DailyTracking
from app.schemas.tracking_schemas import TakeMedicineIn, TrackingRecordOut, TodayStatusOut
from app.database.mongo import medicines_col, daily_logs_col
from loguru import logger


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _count_user_medicines(user_id: str) -> int:
    col = medicines_col()
    return await col.count_documents({"user_id": user_id})


async def _sync_to_mongo(user_id: str, date_str: str, db: AsyncSession) -> bool:
    """
    If ALL medicines for the day are taken, copy the tracking rows to MongoDB
    and remove them from SQLite.  Returns True if sync happened.
    """
    total = await _count_user_medicines(user_id)
    if total == 0:
        return False

    stmt = select(DailyTracking).where(
        DailyTracking.user_id == user_id,
        DailyTracking.date == date_str,
        DailyTracking.taken == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    taken_rows = result.scalars().all()

    if len(taken_rows) < total:
        return False  # not all done yet

    # Build MongoDB document
    log_doc = {
        "user_id": user_id,
        "date": date_str,
        "medicines_taken": [
            {
                "medicine_id": r.medicine_id,
                "taken_at": r.timestamp.isoformat(),
            }
            for r in taken_rows
        ],
        "completed": True,
        "synced_at": datetime.now(timezone.utc),
    }

    col = daily_logs_col()
    await col.update_one(
        {"user_id": user_id, "date": date_str},
        {"$set": log_doc},
        upsert=True,
    )
    logger.success(f"Synced daily log for user={user_id} date={date_str} to MongoDB")

    # Clean up SQLite rows
    for row in taken_rows:
        await db.delete(row)
    await db.commit()

    return True


# ── Public service functions ──────────────────────────────────────────────────

async def mark_taken(
    user_id: str, data: TakeMedicineIn, db: AsyncSession
) -> TrackingRecordOut:
    date_str = data.date or dt_date.today().isoformat()

    # Upsert: find existing row or create new one
    stmt = select(DailyTracking).where(
        DailyTracking.user_id == user_id,
        DailyTracking.medicine_id == data.medicine_id,
        DailyTracking.date == date_str,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row:
        row.taken = True
        row.timestamp = datetime.now(timezone.utc)
    else:
        row = DailyTracking(
            user_id=user_id,
            medicine_id=data.medicine_id,
            date=date_str,
            taken=True,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    # Attempt sync to Mongo after every mark
    await _sync_to_mongo(user_id, date_str, db)

    return TrackingRecordOut.model_validate(row)


async def get_today_status(user_id: str, db: AsyncSession) -> TodayStatusOut:
    date_str = dt_date.today().isoformat()
    total = await _count_user_medicines(user_id)

    stmt = select(DailyTracking).where(
        DailyTracking.user_id == user_id,
        DailyTracking.date == date_str,
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    taken_count = sum(1 for r in rows if r.taken)
    pending = total - taken_count
    pct = (taken_count / total * 100) if total > 0 else 0.0

    # Check if already synced to Mongo
    col = daily_logs_col()
    mongo_log = await col.find_one({"user_id": user_id, "date": date_str})
    synced = mongo_log is not None

    return TodayStatusOut(
        date=date_str,
        total=total,
        taken=taken_count,
        pending=pending,
        adherence_pct=round(pct, 1),
        records=[TrackingRecordOut.model_validate(r) for r in rows],
        synced_to_mongo=synced,
    )
