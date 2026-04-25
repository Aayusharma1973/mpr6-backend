"""
Pydantic schemas for Chat domain.
"""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


# ── PharmEasy structured result ───────────────────────────────────────────────
# Defined BEFORE ChatMessageOut so ChatMessageOut can reference them directly
# without forward references (which cause model_validate issues with SQLAlchemy rows)

class PharmEasyProduct(BaseModel):
    """Single product page result for one medicine."""
    title: str
    url:   str
    image: Optional[str] = None  # CDN image URL from PharmEasy, None if not found


class PharmEasyMedicineResult(BaseModel):
    """All product results for one medicine."""
    medicine: str
    results:  list[PharmEasyProduct]


# ── Chat message schemas ──────────────────────────────────────────────────────

class ChatMessageOut(BaseModel):
    id: int
    user_id: str
    message: str
    sender: Literal["user", "bot"]
    timestamp: datetime
    # Populated on bot messages that triggered PharmEasy search; None otherwise.
    pharmeasy_results: Optional[list[PharmEasyMedicineResult]] = None

    model_config = {"from_attributes": True}


# ── Chat response ─────────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    """
    Response shape from POST /chat and POST /chat/with-image.

    user_message       — the user's message echoed back (saved to DB)
    pre_tool_message   — the LLM's first reply when it answered AND called a tool
                         in the same turn (e.g. explained medicines then searched).
                         None when no tool was called.
    bot_message        — the bot's final plain-text reply (saved to DB, no URLs)
    pharmeasy_results  — populated only when the PharmEasy tool was called;
                         None otherwise so the frontend skips the product card section.
    """
    user_message:      ChatMessageOut
    pre_tool_message:  Optional[ChatMessageOut] = None
    bot_message:       ChatMessageOut
    pharmeasy_results: Optional[list[PharmEasyMedicineResult]] = None


# ── Image-chat schema ─────────────────────────────────────────────────────────

class ChatWithImageMessageIn(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's question about the prescription image",
    )


# ── Legacy / standalone PharmEasy search schemas ──────────────────────────────

class PharmEasyLink(BaseModel):
    title: str
    url:   str


class PharmEasySearchResponse(BaseModel):
    results: list[PharmEasyMedicineResult]