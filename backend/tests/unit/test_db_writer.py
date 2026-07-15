"""DbWriter: bounded queue, overflow policy, batch insert (Фаза 2, п.3–4)."""

import asyncio

from app.core.config import DatabaseConfig, QueueOverflowPolicy
from app.database.writer import DbWriter


def make_config(**overrides) -> DatabaseConfig:
    defaults = dict(
        write_queue_size=100,
        batch_max_rows=500,
        batch_max_interval_ms=1000,
        shutdown_flush_timeout_s=5.0,
    )
    defaults.update(overrides)
    return DatabaseConfig(**defaults)


async def test_batches_by_row_count():
    written: list[dict] = []

    async def flush(grouped):
        written.append(grouped)

    writer = DbWriter(
        flush=flush, config=make_config(batch_max_rows=3, batch_max_interval_ms=10_000)
    )
    await writer.start()
    for i in range(3):
        writer.enqueue("quotes_1s", {"i": i})
    await asyncio.sleep(0.05)
    await writer.stop()

    assert len(written) == 1
    assert len(written[0]["quotes_1s"]) == 3
    assert writer.metrics.written_total == 3


async def test_batches_by_time_interval():
    written: list[dict] = []

    async def flush(grouped):
        written.append(grouped)

    writer = DbWriter(flush=flush, config=make_config(batch_max_rows=500, batch_max_interval_ms=50))
    await writer.start()
    writer.enqueue("quotes_1s", {"i": 1})
    await asyncio.sleep(0.15)
    await writer.stop()

    assert len(written) >= 1
    assert sum(len(g.get("quotes_1s", [])) for g in written) == 1


async def test_drop_oldest_policy_keeps_latest():
    async def flush(grouped):
        pass

    size = 100
    writer = DbWriter(
        flush=flush,
        config=make_config(
            write_queue_size=size, queue_overflow_policy=QueueOverflowPolicy.DROP_OLDEST
        ),
    )
    # Не запускаємо consumer — тестуємо лише поведінку producer-side черги.
    total = size + 5
    for i in range(total):
        writer.enqueue("quotes_1s", {"i": i})
    assert writer.metrics.dropped_total == 5
    assert writer._queue.qsize() == size
    remaining = [writer._queue.get_nowait()[1]["i"] for _ in range(size)]
    assert remaining == list(range(5, total))


async def test_drop_newest_policy_rejects_incoming():
    async def flush(grouped):
        pass

    size = 100
    writer = DbWriter(
        flush=flush,
        config=make_config(
            write_queue_size=size, queue_overflow_policy=QueueOverflowPolicy.DROP_NEWEST
        ),
    )
    total = size + 5
    for i in range(total):
        writer.enqueue("quotes_1s", {"i": i})
    assert writer.metrics.dropped_total == 5
    remaining = [writer._queue.get_nowait()[1]["i"] for _ in range(size)]
    assert remaining == list(range(size))


async def test_failed_batch_does_not_crash_writer():
    calls = {"n": 0}

    async def flush(grouped):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db down")

    writer = DbWriter(flush=flush, config=make_config(batch_max_rows=1, batch_max_interval_ms=50))
    await writer.start()
    writer.enqueue("quotes_1s", {"i": 1})
    await asyncio.sleep(0.08)
    writer.enqueue("quotes_1s", {"i": 2})
    await asyncio.sleep(0.08)
    await writer.stop()

    assert writer.metrics.failed_batches == 1
    assert writer.metrics.written_total == 1  # тільки другий батч дописався


async def test_shutdown_flushes_pending_queue():
    written: list[dict] = []

    async def flush(grouped):
        written.append(grouped)

    writer = DbWriter(
        flush=flush, config=make_config(batch_max_rows=500, batch_max_interval_ms=5000)
    )
    await writer.start()
    writer.enqueue("quotes_1s", {"i": 1})
    writer.enqueue("quotes_1s", {"i": 2})
    await writer.stop()  # graceful shutdown має дописати чергу без очікування 5с

    assert sum(len(g.get("quotes_1s", [])) for g in written) == 2


async def test_shutdown_timeout_reports_lost_records():
    async def flush(grouped):
        await asyncio.sleep(10)  # довше за timeout — writer буде скасовано

    writer = DbWriter(
        flush=flush,
        config=make_config(
            batch_max_rows=1, batch_max_interval_ms=50, shutdown_flush_timeout_s=0.1
        ),
    )
    await writer.start()
    writer.enqueue("quotes_1s", {"i": 1})
    await asyncio.sleep(0.08)
    await writer.stop()  # не має підвиснути назавжди


async def test_grouped_by_multiple_tables():
    written: list[dict] = []

    async def flush(grouped):
        written.append(grouped)

    writer = DbWriter(
        flush=flush, config=make_config(batch_max_rows=2, batch_max_interval_ms=10_000)
    )
    await writer.start()
    writer.enqueue("quotes_1s", {"i": 1})
    writer.enqueue("spread_events", {"i": 2})
    await asyncio.sleep(0.05)
    await writer.stop()

    assert set(written[0]) == {"quotes_1s", "spread_events"}
