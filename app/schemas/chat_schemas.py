"""
Pydantic schemas for Chat domain.
"""
from datetime import datetime
from typing import Literal
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
    bot_message: ChatMessageOut
