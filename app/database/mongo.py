"""
MongoDB connection using Motor (async driver).
"""
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from loguru import logger

settings = get_settings()

# Module-level client / db — initialised in lifespan
_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    if _client is None:
        raise RuntimeError("MongoDB client not initialised. Call connect_mongo() first.")
    return _client


def get_db():
    return get_client()[settings.mongo_db_name]


async def connect_mongo():
    global _client
    logger.info(f"Connecting to MongoDB at {settings.mongo_uri} ...")
    _client = AsyncIOMotorClient(settings.mongo_uri)
    # Force a ping to validate the connection
    await _client.admin.command("ping")
    logger.success("MongoDB connected ✓")


async def close_mongo():
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed.")


# ── Collection helpers ────────────────────────────────────────────────────────

def users_col():
    return get_db()["users"]


def medicines_col():
    return get_db()["medicines"]


def daily_logs_col():
    return get_db()["daily_logs"]
