"""Оркестрація Фази 2.1: партиції, downsampling, retention, метрики розміру.

Працює як фоновий job (аналогічно HistoryRecorder): періодично створює
майбутні партиції quotes_1s, доганяє downsampling, видаляє застарілі дані
за retention-політикою кожного рівня. `spread_events` має вищий пріоритет
і за замовчуванням зберігається постійно (план, Фаза 2.1 п.3 / 2.2 п.5).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import RetentionConfig
from app.database.partitioning import PartitionManager
from app.database.retention import cutoff_ms
from app.quote_cache.cache import now_ms
from app.services.downsampler import LEVELS, Downsampler

logger = logging.getLogger(__name__)

# (таблиця, поле retention-конфігу) для downsample-рівнів + spread_events.
_DOWNSAMPLE_RETENTION_FIELDS = {
    "quotes_10s": "downsample_10s_retention_days",
    "quotes_1m": "downsample_1m_retention_days",
    "quotes_5m": "downsample_5m_retention_days",
}


@dataclass
class RetentionMetrics:
    last_run_at_ms: int | None = None
    partitions_created: int = 0
    partitions_dropped: int = 0
    downsampled_rows: dict[str, int] = field(default_factory=dict)
    rows_deleted: dict[str, int] = field(default_factory=dict)
    storage_bytes: dict[str, int] = field(default_factory=dict)
    last_error: str | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "last_run_at_ms": self.last_run_at_ms,
            "partitions_created": self.partitions_created,
            "partitions_dropped": self.partitions_dropped,
            "downsampled_rows": dict(self.downsampled_rows),
            "rows_deleted": dict(self.rows_deleted),
            "storage_bytes": dict(self.storage_bytes),
            "last_error": self.last_error,
        }


class RetentionManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: RetentionConfig,
        partition_manager: PartitionManager | None = None,
        downsampler: Downsampler | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._partitions = partition_manager or PartitionManager(session_factory)
        self._downsampler = downsampler or Downsampler(session_factory)
        self.metrics = RetentionMetrics()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="retention-manager")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self, current_ms: int | None = None) -> RetentionMetrics:
        current = current_ms if current_ms is not None else now_ms()
        try:
            created = await self._partitions.ensure_partitions(
                current, ahead_days=self._config.partition_ahead_days
            )
            dropped = await self._partitions.drop_old_partitions(
                current, retention_days=self._config.raw_retention_days
            )
            downsampled = await self._downsampler.run(current)
            deleted = await self._delete_expired_rows(current)
            storage = await self._measure_storage()

            self.metrics.partitions_created = len(created)
            self.metrics.partitions_dropped = len(dropped)
            self.metrics.downsampled_rows = downsampled
            self.metrics.rows_deleted = deleted
            self.metrics.storage_bytes = storage
            self.metrics.last_error = None
        except Exception as exc:  # noqa: BLE001 - maintenance не має вбити застосунок
            self.metrics.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Retention maintenance run failed")
        self.metrics.last_run_at_ms = current
        return self.metrics

    async def _delete_expired_rows(self, current_ms: int) -> dict[str, int]:
        deleted: dict[str, int] = {}
        async with self._session_factory() as session:
            for level in LEVELS:
                retention_days = getattr(self._config, _DOWNSAMPLE_RETENTION_FIELDS[level.table])
                cutoff = cutoff_ms(current_ms, retention_days)
                # level.table is one of the fixed LEVELS table names, not user input.
                delete_sql = (
                    f"DELETE FROM {level.table} WHERE bucket_timestamp < :cutoff"  # noqa: S608
                )
                result = await session.execute(text(delete_sql), {"cutoff": cutoff})
                deleted[level.table] = cast("CursorResult[Any]", result).rowcount or 0
            if self._config.spread_events_retention_days:
                cutoff = cutoff_ms(current_ms, self._config.spread_events_retention_days)
                result = await session.execute(
                    text("DELETE FROM spread_events WHERE end_timestamp < :cutoff"),
                    {"cutoff": cutoff},
                )
                deleted["spread_events"] = cast("CursorResult[Any]", result).rowcount or 0
            await session.commit()
        return deleted

    async def _measure_storage(self) -> dict[str, int]:
        # quotes_1s is RANGE-partitioned: the parent relation itself has no
        # heap (pg_total_relation_size on it returns 0) — actual data lives
        # in per-day child partitions, so its size must be summed over them.
        plain_tables = ["spread_events", "quotes_10s", "quotes_1m", "quotes_5m"]
        sizes: dict[str, int] = {}
        async with self._session_factory() as session:
            for table in plain_tables:
                result = await session.execute(
                    text("SELECT pg_total_relation_size(:table)"), {"table": table}
                )
                sizes[table] = result.scalar_one()
            result = await session.execute(
                text(
                    "SELECT COALESCE(sum(pg_total_relation_size(child.oid)), 0) "
                    "FROM pg_inherits "
                    "JOIN pg_class parent ON pg_inherits.inhparent = parent.oid "
                    "JOIN pg_class child ON pg_inherits.inhrelid = child.oid "
                    "WHERE parent.relname = 'quotes_1s'"
                )
            )
            # SUM() over bigint returns numeric in Postgres -> Decimal here.
            sizes["quotes_1s"] = int(result.scalar_one())
        return sizes

    async def _loop(self) -> None:
        interval_s = self._config.maintenance_interval_hours * 3600
        while True:
            await self.run_once()
            await asyncio.sleep(interval_s)
