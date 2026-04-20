"""
app/services/chat_service.py
─────────────────────────────
Business logic for Chat.

Two entry-points:
  send_message(user_id, data, db)                              — text-only chat
  send_message_with_image(user_id, message, image_bytes, db)   — image+text chat

Both use the SAME SQLite chat_messages table so history is always unified.

ChatResponse now carries an optional `pharmeasy_results` field that is
populated only when the PharmEasy tool was called — the frontend renders
product cards from this structured data, while `bot_message.message` stays
clean plain text (no URLs).
"""

from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.sqlite_models import ChatMessage
from app.schemas.chat_schemas import (
    ChatMessageIn,
    ChatMessageOut,
    ChatResponse,
    PharmEasyMedicineResult,
    PharmEasyProduct,
)
from app.database.mongo import medicines_col
from app.ai import agent_service, qwen_ocr
from loguru import logger


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_history_as_turns(user_id: str, db: AsyncSession) -> list[dict]:
    """Load chat history and convert to [{"role": ..., "content": ...}] format."""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.timestamp.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    turns = []
    for row in rows:
        role = "user" if row.sender == "user" else "assistant"
        turns.append({"role": role, "content": row.message})
    return turns


async def _get_user_medicines(user_id: str) -> list[dict]:
    """Fetch user's current medicines from MongoDB for LLM context."""
    try:
        col    = medicines_col()
        cursor = col.find({"user_id": user_id}, {"name": 1, "dosage": 1, "frequency": 1})
        docs   = await cursor.to_list(length=50)
        return [
            {
                "name":      d.get("name"),
                "dosage":    d.get("dosage"),
                "frequency": d.get("frequency"),
            }
            for d in docs
        ]
    except Exception as exc:
        logger.warning(f"Could not fetch medicines for user {user_id}: {exc}")
        return []


async def _persist_pair(
    user_id: str,
    user_text: str,
    bot_text: str,
    db: AsyncSession,
) -> tuple[ChatMessage, ChatMessage]:
    """Save a user message + bot reply pair to SQLite."""
    user_msg = ChatMessage(
        user_id=user_id,
        message=user_text,
        sender="user",
        timestamp=datetime.now(timezone.utc),
    )
    bot_msg = ChatMessage(
        user_id=user_id,
        message=bot_text,
        sender="bot",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(user_msg)
    db.add(bot_msg)
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(bot_msg)
    return user_msg, bot_msg


def _parse_pharmeasy_results(
    raw: list[dict] | None,
) -> list[PharmEasyMedicineResult] | None:
    """
    Convert the raw list from agent_service into validated Pydantic models.
    Returns None if raw is None or empty so the frontend key is absent.
    """
    if not raw:
        return None
    parsed = []
    for item in raw:
        products = [
            PharmEasyProduct(title=p["title"], url=p["url"])
            for p in item.get("results", [])
        ]
        parsed.append(
            PharmEasyMedicineResult(
                medicine=item["medicine"],
                results=products,
            )
        )
    return parsed or None


# ── Public service functions ──────────────────────────────────────────────────

async def send_message(
    user_id: str,
    data: ChatMessageIn,
    db: AsyncSession,
) -> ChatResponse:
    """
    Text-only chat turn.
    Loads full history → calls agent (with tool loop) → saves pair → returns response.
    """
    history   = await _get_history_as_turns(user_id, db)
    medicines = await _get_user_medicines(user_id)

    # agent_service.chat_reply now returns a ChatReplyResult dataclass
    result = await agent_service.chat_reply(
        user_message=data.message,
        history=history,
        medicines=medicines,
    )

    bot_text = result.content
    user_msg, bot_msg = await _persist_pair(user_id, data.message, bot_text, db)

    logger.debug(f"Chat [text] user={user_id}: {data.message[:60]}")

    return ChatResponse(
        user_message=ChatMessageOut.model_validate(user_msg),
        bot_message=ChatMessageOut.model_validate(bot_msg),
        pharmeasy_results=_parse_pharmeasy_results(result.pharmeasy_results),
    )


async def send_message_with_image(
    user_id: str,
    message: str,
    image_bytes: bytes,
    db: AsyncSession,
) -> ChatResponse:
    """
    Image + text chat turn.
    Uses Qwen VLM — tool-calling is not supported here (image chat is
    explanation-only), so pharmeasy_results is always None.
    """
    history = await _get_history_as_turns(user_id, db)
    bot_text = await qwen_ocr.answer_with_image(
        image_bytes=image_bytes,
        question=message,
        history=history,
    )
    user_text_stored = f"[image] {message}"
    user_msg, bot_msg = await _persist_pair(user_id, user_text_stored, bot_text, db)
    logger.debug(f"Chat [image] user={user_id}: {message[:60]}")
    return ChatResponse(
        user_message=ChatMessageOut.model_validate(user_msg),
        bot_message=ChatMessageOut.model_validate(bot_msg),
        pharmeasy_results=None,   # image chat doesn't trigger PharmEasy search
    )


async def get_history(
    user_id: str,
    db: AsyncSession,
    limit: int = 50,
) -> list[ChatMessageOut]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.timestamp.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [ChatMessageOut.model_validate(r) for r in rows]