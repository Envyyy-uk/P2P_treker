"""Async DB writer (Фаза 2, п.3–4).

Bounded asyncio.Queue між collectors і БД: запис ніколи не блокує
збір ринкових даних. Batch insert — за кількістю рядків або часовим
інтервалом, що спрацює першим. Політика переповнення явна і
конфігурується; всі втрати підраховуються.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import DatabaseConfig, QueueOverflowPolicy

logger = logging.getLogger(__name__)

# Один елемент черги: (назва таблиці, значення рядка).
WriteItem = tuple[str, dict[str, Any]]
# Функція фактичного запису батчу, згрупованого за таблицями.
FlushFn = Callable[[dict[str, list[dict[str, Any]]]], Awaitable[None]]


@dataclass
class WriterMetrics:
    enqueued_total: int = 0
    written_total: int = 0
    dropped_total: int = 0
    failed_batches: int = 0
    batches_total: int = 0
    last_batch_size: int = 0
    last_write_latency_ms: float = 0.0
    queue_size: int = 0

    def snapshot(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class DbWriter:
    flush: FlushFn
    config: DatabaseConfig
    metrics: WriterMetrics = field(default_factory=WriterMetrics)

    def __post_init__(self) -> None:
        self._queue: asyncio.Queue[WriteItem] = asyncio.Queue(maxsize=self.config.write_queue_size)
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    # ---- producer side (collectors) — синхронний, ніколи не блокує ----------

    def enqueue(self, table: str, row: dict[str, Any]) -> bool:
        item = (table, row)
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            policy = self.config.queue_overflow_policy
            if policy is QueueOverflowPolicy.DROP_NEWEST:
                self._drop(1)
                return False
            if policy is QueueOverflowPolicy.DROP_OLDEST:
                try:
                    self._queue.get_nowait()
                    self._drop(1)
                except asyncio.QueueEmpty:  # pragma: no cover - гонка малоймовірна
                    pass
                try:
                    self._queue.put_nowait(item)
                except asyncio.QueueFull:  # pragma: no cover
                    self._drop(1)
                    return False
            else:  # BLOCK свідомо не підтримуємо для live collectors (план)
                self._drop(1)
                logger.error("DB queue full with policy=%s; record dropped", policy.value)
                return False
        self.metrics.enqueued_total += 1
        self.metrics.queue_size = self._queue.qsize()
        return True

    def _drop(self, n: int) -> None:
        self.metrics.dropped_total += n
        if self.metrics.dropped_total % 1000 == 1:  # не спамити на кожен запис
            logger.error("DB queue overflow: %d records dropped so far", self.metrics.dropped_total)

    # ---- consumer side -------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="db-writer")

    async def stop(self) -> None:
        """Graceful shutdown: дописати чергу з таймаутом і зупинитись."""
        self._stopping = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=self.config.shutdown_flush_timeout_s)
            except TimeoutError:
                logger.error("DB flush timed out on shutdown; %d records lost", self._queue.qsize())
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

    async def _run(self) -> None:
        interval_s = self.config.batch_max_interval_ms / 1000.0
        while not (self._stopping and self._queue.empty()):
            batch = await self._collect_batch(interval_s)
            if batch:
                await self._write(batch)
        logger.info("DB writer drained and stopped")

    async def _collect_batch(self, interval_s: float) -> list[WriteItem]:
        """Набирає батч до batch_max_rows або поки не сплине інтервал."""
        batch: list[WriteItem] = []
        deadline = time.monotonic() + interval_s
        while len(batch) < self.config.batch_max_rows:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(self._queue.get(), timeout=remaining))
            except TimeoutError:
                break
            if self._stopping and self._queue.empty():
                break
        self.metrics.queue_size = self._queue.qsize()
        return batch

    async def _write(self, batch: list[WriteItem]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for table, row in batch:
            grouped.setdefault(table, []).append(row)
        started = time.monotonic()
        try:
            await self.flush(grouped)
        except Exception:  # noqa: BLE001 - збій БД не має вбити writer
            self.metrics.failed_batches += 1
            logger.exception("Batch insert failed; %d records lost", len(batch))
            return
        self.metrics.batches_total += 1
        self.metrics.last_batch_size = len(batch)
        self.metrics.written_total += len(batch)
        self.metrics.last_write_latency_ms = (time.monotonic() - started) * 1000.0
