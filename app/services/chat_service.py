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
    pharmeasy_results: list[dict] | None = None,
    pre_tool_text: str | None = None,
) -> tuple[ChatMessage, ChatMessage | None, ChatMessage]:
    """
    Save a user message + optional pre-tool bot message + final bot reply to SQLite.
    Returns (user_msg, pre_tool_msg_or_None, bot_msg).
    """
    import json as _json
    now = datetime.now(timezone.utc)

    user_msg = ChatMessage(
        user_id=user_id,
        message=user_text,
        sender="user",
        timestamp=now,
        pharmeasy_results=None,
    )

    pre_tool_msg = None
    if pre_tool_text:
        pre_tool_msg = ChatMessage(
            user_id=user_id,
            message=pre_tool_text,
            sender="bot",
            timestamp=now,
            pharmeasy_results=None,  # no results yet at this point
        )

    bot_msg = ChatMessage(
        user_id=user_id,
        message=bot_text,
        sender="bot",
        timestamp=now,
        pharmeasy_results=_json.dumps(pharmeasy_results) if pharmeasy_results else None,
    )

    db.add(user_msg)
    if pre_tool_msg:
        db.add(pre_tool_msg)
    db.add(bot_msg)
    await db.commit()
    await db.refresh(user_msg)
    if pre_tool_msg:
        await db.refresh(pre_tool_msg)
    await db.refresh(bot_msg)
    return user_msg, pre_tool_msg, bot_msg


def _bot_msg_out(row: ChatMessage) -> ChatMessageOut:
    """
    Build a ChatMessageOut from a ChatMessage row, deserializing the
    JSON pharmeasy_results column back into structured Pydantic models.

    We must NOT let model_validate see the raw JSON string in pharmeasy_results
    because Pydantic would try to validate a str as list[PharmEasyMedicineResult]
    and raise. Instead we pass pharmeasy_results=None to model_validate, then
    set the deserialized value on the resulting object.
    """
    import json as _json

    # Temporarily hide the raw JSON so model_validate only sees None
    raw_json = row.pharmeasy_results
    row.pharmeasy_results = None

    out = ChatMessageOut.model_validate(row)

    # Restore on the row (avoid mutating the ORM object permanently)
    row.pharmeasy_results = raw_json

    if raw_json:
        try:
            out.pharmeasy_results = _parse_pharmeasy_results(_json.loads(raw_json))
        except Exception:
            out.pharmeasy_results = None
    return out


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
            PharmEasyProduct(title=p["title"], url=p["url"], image=p.get("image"))
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
    user_msg, pre_tool_msg, bot_msg = await _persist_pair(
        user_id, data.message, bot_text, db,
        pharmeasy_results=result.pharmeasy_results,
        pre_tool_text=result.pre_tool_content,
    )

    logger.debug(f"Chat [text] user={user_id}: {data.message[:60]}")

    return ChatResponse(
        user_message=ChatMessageOut.model_validate(user_msg),
        pre_tool_message=(
            ChatMessageOut.model_validate(pre_tool_msg) if pre_tool_msg else None
        ),
        bot_message=_bot_msg_out(bot_msg),
        pharmeasy_results=_parse_pharmeasy_results(result.pharmeasy_results),
    )


async def send_message_with_image(
    user_id: str,
    message: str,
    image_bytes: bytes,
    db: AsyncSession,
) -> ChatResponse:
    """
    Image + text chat turn — two-stage pipeline:

    Stage 1 — Qwen VLM reads the image and produces a structured text
              description (medicines, dosages, any visible instructions).
              Qwen cannot call tools, but it can see the image.

    Stage 2 — Ollama agent receives the Qwen description as injected context
              and runs the full tool-calling loop.  If the user asked to
              order / find medicines, the PharmEasy scraper fires here.

    Both the user message and bot reply go to the same SQLite history table
    so context stays unified across text and image turns.
    """
    history   = await _get_history_as_turns(user_id, db)
    medicines = await _get_user_medicines(user_id)

    # ── Stage 1: Qwen reads the image ────────────────────────────────────────
    image_description = await qwen_ocr.answer_with_image(
        image_bytes=image_bytes,
        question=message,
        history=history,
    )

    # ── Stage 2: Ollama tool loop with image context injected ─────────────────
    # We augment the user message with Qwen's image description so Ollama
    # has the prescription content even though it can't see the image itself.
    augmented_message = (
        f"{message}"
        f"[Prescription image contents as read by the OCR model:]"
        f"{image_description}"
    )

    result = await agent_service.chat_reply(
        user_message=augmented_message,
        history=history,
        medicines=medicines,
    )

    # Store the user message without the injected OCR dump — keep history clean
    user_text_stored = f"[image] {message}"
    user_msg, pre_tool_msg, bot_msg = await _persist_pair(
        user_id, user_text_stored, result.content, db,
        pharmeasy_results=result.pharmeasy_results,
        pre_tool_text=result.pre_tool_content,
    )

    logger.debug(f"Chat [image] user={user_id}: {message[:60]}")
    return ChatResponse(
        user_message=ChatMessageOut.model_validate(user_msg),
        pre_tool_message=(
            ChatMessageOut.model_validate(pre_tool_msg) if pre_tool_msg else None
        ),
        bot_message=_bot_msg_out(bot_msg),
        pharmeasy_results=_parse_pharmeasy_results(result.pharmeasy_results),
    )


async def clear_history(user_id: str, db: AsyncSession) -> dict:
    """Delete all chat messages for the user from SQLite."""
    from sqlalchemy import delete
    await db.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
    await db.commit()
    logger.debug(f"Chat history cleared for user={user_id}")
    return {"detail": "Chat history cleared."}


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
    return [
        _bot_msg_out(r) if r.sender == "bot" else ChatMessageOut.model_validate(r)
        for r in rows
    ]