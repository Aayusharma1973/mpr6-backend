"""
Business logic for Chat History (SQLite).
"""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.sqlite_models import ChatMessage
from app.schemas.chat_schemas import ChatMessageIn, ChatMessageOut, ChatResponse
from loguru import logger


# Very simple rule-based bot — swap with an LLM call if desired
_BOT_REPLIES = {
    "interaction": "Please consult your pharmacist about drug interactions. I can flag common ones — which medicines would you like me to check?",
    "missed": "Missing doses can affect treatment. Try setting a reminder. Shall I help you configure one?",
    "side effect": "Side effects vary by medication. Can you tell me which medicine and what you're experiencing?",
    "refill": "Looks like some of your prescriptions may be running low. Check the Meds tab for refill alerts.",
    "dosage": "Always follow your doctor's prescribed dosage. Would you like me to show your current dosage schedule?",
}

_DEFAULT_REPLY = (
    "I'm RxGuardian AI 🤖. I can help with drug interactions, dosage reminders, and prescription analysis. "
    "What would you like to know?"
)


def _generate_bot_reply(user_message: str) -> str:
    lower = user_message.lower()
    for keyword, reply in _BOT_REPLIES.items():
        if keyword in lower:
            return reply
    return _DEFAULT_REPLY


async def send_message(
    user_id: str, data: ChatMessageIn, db: AsyncSession
) -> ChatResponse:
    # Persist user message
    user_msg = ChatMessage(
        user_id=user_id,
        message=data.message,
        sender="user",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(user_msg)
    await db.flush()  # get the auto-increment id

    # Generate and persist bot reply
    bot_text = _generate_bot_reply(data.message)
    bot_msg = ChatMessage(
        user_id=user_id,
        message=bot_text,
        sender="bot",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(bot_msg)
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(bot_msg)

    logger.debug(f"Chat [{user_id}] user: {data.message[:60]} | bot: {bot_text[:60]}")

    return ChatResponse(
        user_message=ChatMessageOut.model_validate(user_msg),
        bot_message=ChatMessageOut.model_validate(bot_msg),
    )


async def get_history(
    user_id: str, db: AsyncSession, limit: int = 50
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
