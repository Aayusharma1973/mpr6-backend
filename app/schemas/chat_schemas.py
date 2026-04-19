"""
Pydantic schemas for Chat domain.
"""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ChatMessageOut(BaseModel):
    id: int
    user_id: str
    message: str
    sender: Literal["user", "bot"]
    timestamp: datetime

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    user_message: ChatMessageOut
    bot_message:  ChatMessageOut


# ── Image-chat schema ─────────────────────────────────────────────────────────
# Used by POST /chat/with-image (multipart form)
# The image itself is passed as UploadFile — this schema carries only the text.

class ChatWithImageMessageIn(BaseModel):
    """
    Text part of an image+text chat message.
    The image is a separate UploadFile field in the route.
    """
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's question about the prescription image",
    )


# ── PharmEasy search result schemas ──────────────────────────────────────────

class PharmEasyLink(BaseModel):
    title: str
    url:   str


class PharmEasyMedicineResult(BaseModel):
    medicine: str
    links:    list[PharmEasyLink]
    error:    Optional[str] = None


class PharmEasySearchResponse(BaseModel):
    results: list[PharmEasyMedicineResult]