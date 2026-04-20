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


# ── PharmEasy structured result ───────────────────────────────────────────────

class PharmEasyProduct(BaseModel):
    """Single product page result for one medicine."""
    title: str
    url:   str


class PharmEasyMedicineResult(BaseModel):
    """All product results for one medicine."""
    medicine: str
    results:  list[PharmEasyProduct]


# ── Chat response ─────────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    """
    Response shape from POST /chat and POST /chat/with-image.

    user_message       — the user's message echoed back (saved to DB)
    bot_message        — the bot's plain-text reply (saved to DB, no URLs)
    pharmeasy_results  — populated only when the PharmEasy tool was called;
                         None otherwise so the frontend skips the product card section.

    Example when tool was called:
    {
        "user_message": { ... },
        "bot_message":  { ... "message": "Found your medicines on PharmEasy! 🎉" },
        "pharmeasy_results": [
            {
                "medicine": "Metformin",
                "results": [
                    {"title": "Glycomet Sr 500mg Strip Of 20 Tablets ...", "url": "https://pharmeasy.in/..."},
                    {"title": "Istamet 50/500mg Strip Of 15 Tablets ...",  "url": "https://pharmeasy.in/..."},
                    {"title": "Glyciphage Sr 500mg Strip Of 10 Tablets ...","url": "https://pharmeasy.in/..."}
                ]
            },
            {
                "medicine": "Atorvastatin",
                "results": [ ... ]
            }
        ]
    }
    """
    user_message:      ChatMessageOut
    bot_message:       ChatMessageOut
    pharmeasy_results: Optional[list[PharmEasyMedicineResult]] = None


# ── Image-chat schema ─────────────────────────────────────────────────────────

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


# ── Legacy / standalone PharmEasy search schemas ──────────────────────────────
# Kept for any routes that expose a direct /search endpoint.

class PharmEasyLink(BaseModel):
    title: str
    url:   str


class PharmEasySearchResponse(BaseModel):
    results: list[PharmEasyMedicineResult]