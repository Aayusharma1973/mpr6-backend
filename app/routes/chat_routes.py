"""
app/routes/chat_routes.py
──────────────────────────
Two chat endpoints that share the same SQLite history table:

  POST /chat           — text-only message  (JSON body)
  POST /chat/with-image — text + image       (multipart form)
  GET  /chat/history   — full history for current user
"""

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat_schemas import (
    ChatMessageIn,
    ChatMessageOut,
    ChatResponse,
)
from app.services.chat_service import (
    send_message as send_chat_message,
    send_message_with_image as send_image_chat_message,
    get_history as get_chat_history,
    clear_history as clear_chat_history,
)
from app.auth.dependencies import get_current_user
from app.database.sqlite import get_session

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "",
    response_model=ChatResponse,
    status_code=201,
    summary="Send a text message to RxGuardian AI",
)
async def send_message(
    body: ChatMessageIn,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Send a plain-text message. The AI replies using full conversation history
    and the user's current medicine list for context.
    """
    return await send_chat_message(current_user["id"], body, db)


@router.post(
    "/with-image",
    response_model=ChatResponse,
    status_code=201,
    summary="Send a message with a prescription image",
)
async def chat_with_image(
    message: str = Form(..., min_length=1, max_length=2000, description="Your question about the image"),
    file: UploadFile = File(..., description="Prescription image (JPEG / PNG)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Send a text message alongside a prescription image.
    The Qwen VLM answers with full awareness of the previous conversation history —
    so switching between text and image messages mid-chat works seamlessly.
    Both the user message and bot reply are saved to the same history table as
    regular text messages.
    """
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files (JPEG/PNG) are accepted.",
        )
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image file is empty.",
        )

    return await send_image_chat_message(
        user_id=current_user["id"],
        message=message,
        image_bytes=image_bytes,
        db=db,
    )


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
    """
    Returns chat history ordered oldest → newest.
    Includes both text-only and image-chat turns (image turns are stored as
    '[image] <user question>' so context is preserved).
    """
    return await get_chat_history(current_user["id"], db, limit=limit)

@router.delete(
    "/history",
    status_code=200,
    summary="Clear all chat history for the current user",
)
async def clear_history(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Permanently deletes all chat messages for the current user from SQLite.
    Cannot be undone.
    """
    return await clear_chat_history(current_user["id"], db)