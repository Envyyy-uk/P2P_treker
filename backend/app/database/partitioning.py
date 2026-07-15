"""Партиціонування quotes_1s за днями (Фаза 2.1, п.1).

quotes_1s — RANGE-партиціонована таблиця (PARTITION BY RANGE (timestamp)),
див. міграцію 0002. Тут — керування партиціями в рантаймі: створення
майбутніх діб і видалення застарілих (retention).
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.retention import DAY_MS, day_bounds_ms, day_starts_in_range, partition_name_for

logger = logging.getLogger(__name__)

_PARTITION_PREFIX = "quotes_1s_"


class PartitionManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_partitions(
        self, now_ms: int, ahead_days: int, behind_days: int = 1
    ) -> list[str]:
        """Створює денні партиції quotes_1s для [сьогодні-behind, сьогодні+ahead].

        Ідемпотентно: CREATE TABLE IF NOT EXISTS. Партиції-сироти (створені,
        але вже поза вікном) видаляються окремо через drop_old_partitions.
        """
        today_start = day_bounds_ms(now_ms)[0]
        from_ms = today_start - behind_days * DAY_MS
        to_ms = today_start + ahead_days * DAY_MS
        created: list[str] = []
        async with self._session_factory() as session:
            for day_start in day_starts_in_range(from_ms, to_ms):
                day_end = day_start + DAY_MS
                name = partition_name_for(day_start)
                # DDL (CREATE TABLE ... PARTITION OF) doesn't support bind
                # parameters over asyncpg; day_start/day_end are ints we
                # computed ourselves, so inlining them is safe.
                await session.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF quotes_1s "
                        f"FOR VALUES FROM ({day_start}) TO ({day_end})"
                    )
                )
                created.append(name)
            await session.commit()
        return created

    async def existing_partitions(self) -> list[str]:
        """Список поточних партицій quotes_1s (крім default), з `pg_inherits`."""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT child.relname FROM pg_inherits "
                    "JOIN pg_class parent ON pg_inherits.inhparent = parent.oid "
                    "JOIN pg_class child ON pg_inherits.inhrelid = child.oid "
                    "WHERE parent.relname = 'quotes_1s' AND child.relname LIKE :prefix"
                ),
                {"prefix": f"{_PARTITION_PREFIX}%"},
            )
            return [row[0] for row in result.fetchall()]

    async def drop_old_partitions(self, now_ms: int, retention_days: int) -> list[str]:
        """Видаляє партиції, повністю старіші за retention_days."""
        cutoff_day_start = day_bounds_ms(now_ms)[0] - retention_days * DAY_MS
        dropped: list[str] = []
        names = await self.existing_partitions()
        async with self._session_factory() as session:
            for name in names:
                date_part = name.removeprefix(_PARTITION_PREFIX)
                if len(date_part) != 8 or not date_part.isdigit():
                    continue  # неочікуване ім'я — не чіпаємо
                partition_day_start = _parse_partition_day(name)
                if partition_day_start < cutoff_day_start:
                    await session.execute(text(f"DROP TABLE IF EXISTS {name}"))
                    dropped.append(name)
            await session.commit()
        if dropped:
            logger.info("Dropped %d expired quotes_1s partitions: %s", len(dropped), dropped)
        return dropped


def _parse_partition_day(name: str) -> int:
    from datetime import UTC, datetime

    date_part = name.removeprefix(_PARTITION_PREFIX)
    dt = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)
