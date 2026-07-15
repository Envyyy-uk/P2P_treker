"""Batch insert історичних даних (Фаза 2, п.4)."""

from typing import Any

from sqlalchemy import Table, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Quote1s, SpreadEvent

TABLES: dict[str, Table] = {
    Quote1s.__tablename__: Quote1s.__table__,  # type: ignore[dict-item]
    SpreadEvent.__tablename__: SpreadEvent.__table__,  # type: ignore[dict-item]
}


class MarketDataRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def bulk_insert(self, rows_by_table: dict[str, list[dict[str, Any]]]) -> None:
        """Один батч = одна транзакція; multi-row INSERT на таблицю."""
        async with self._session_factory() as session:
            async with session.begin():
                for table_name, rows in rows_by_table.items():
                    if rows:
                        await session.execute(insert(TABLES[table_name]), rows)
