"""
Chat routes — send a message and retrieve history.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.chat_schemas import ChatMessageIn, ChatMessageOut, ChatResponse
from app.services import chat_service
from app.auth.dependencies import get_current_user
from app.database.sqlite import get_session

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "",
    response_model=ChatResponse,
    status_code=201,
    summary="Send a message to RxGuardian AI",
)
async def send_message(
    body: ChatMessageIn,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Sends a user message and returns both the user message and the AI bot reply.
    Both are persisted in SQLite.
    """
    return await chat_service.send_message(current_user["id"], body, db)


@router.get(
    "/history",
    response_model=list[ChatMessageOut],
    summary="Get chat history for the current user",
)
async def get_history(
    limit: int = Query(default=50, ge=1, le=200, description="Max messages to return"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await chat_service.get_history(current_user["id"], db, limit=limit)
