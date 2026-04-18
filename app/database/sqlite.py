"""
SQLite database using SQLAlchemy (async via aiosqlite).
Used for:
  - Chat history
  - Daily medicine tracking (before sync to Mongo)
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings
from loguru import logger

settings = get_settings()

DATABASE_URL = f"sqlite+aiosqlite:///{settings.sqlite_db_path}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,           # set True to log SQL queries during dev
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_sqlite():
    """Create all tables if they don't exist."""
    # Import models so SQLAlchemy registers them before create_all
    import app.models.sqlite_models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.success("SQLite tables created ✓")


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        yield session
