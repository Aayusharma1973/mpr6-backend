"""
Daily medicine tracking routes.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.tracking_schemas import TakeMedicineIn, TrackingRecordOut, TodayStatusOut
from app.services import tracking_service
from app.auth.dependencies import get_current_user
from app.database.sqlite import get_session

router = APIRouter(prefix="/track", tags=["Daily Tracking"])


@router.post(
    "/take",
    response_model=TrackingRecordOut,
    status_code=201,
    summary="Mark a medicine as taken",
)
async def take_medicine(
    body: TakeMedicineIn,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Mark a medicine dose as taken for a given date (defaults to today).
    If ALL medicines for that day are marked taken, the data is automatically
    synced from SQLite → MongoDB daily_logs collection.
    """
    return await tracking_service.mark_taken(current_user["id"], body, db)


@router.get(
    "/today",
    response_model=TodayStatusOut,
    summary="Get today's medicine tracking status",
)
async def today_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Returns adherence summary for today: total medicines, taken, pending,
    and whether today's log has been synced to MongoDB.
    """
    return await tracking_service.get_today_status(current_user["id"], db)
