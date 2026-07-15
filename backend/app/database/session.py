"""Engine/session факторія та перевірка доступності БД при старті."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import DatabaseConfig

logger = logging.getLogger(__name__)


def build_engine(config: DatabaseConfig) -> AsyncEngine:
    return create_async_engine(config.dsn.get_secret_value(), pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - будь-яка причина = БД недоступна
        logger.critical("Database unavailable: %s: %s", type(exc).__name__, exc)
        return False
