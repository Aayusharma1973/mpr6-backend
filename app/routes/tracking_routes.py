"""
Daily medicine tracking routes.
"""
from fastapi import APIRouter, Depends
from app.schemas.tracking_schemas import (
    TakeMedicineIn, 
    TodayStatusOut, 
    WeeklyStatusOut
)
from app.services import tracking_service
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/track", tags=["Daily Tracking"])


@router.post(
    "/take",
    status_code=201,
    summary="Mark a medicine as taken",
)
async def take_medicine(
    body: TakeMedicineIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Mark a medicine dose as taken for today.
    The backend automatically registers the date and time.
    Data is stored directly in MongoDB.
    """
    return await tracking_service.mark_taken(current_user["id"], body)


@router.get(
    "/today",
    response_model=TodayStatusOut,
    summary="Get today's medicine tracking status",
)
async def today_status(
    current_user: dict = Depends(get_current_user),
):
    """
    Returns adherence summary for today: total medicines, taken, pending,
    and missed along with their scheduled times.
    """
    return await tracking_service.get_today_status(current_user["id"])


@router.get(
    "/weekly",
    response_model=WeeklyStatusOut,
    summary="Get last 7 days medicine tracking status",
)
async def weekly_status(
    current_user: dict = Depends(get_current_user),
):
    """
    Returns adherence summary for the last 7 days.
    """
    return await tracking_service.get_weekly_status(current_user["id"])
