"""RetentionManager: оркестрація partition/downsample/delete через фейкові
залежності (без реальної БД) — стиль Фази 2 (FakeSession/моки)."""

from unittest.mock import AsyncMock

from app.core.config import RetentionConfig
from app.services.retention_manager import RetentionManager


def make_config(**overrides) -> RetentionConfig:
    defaults = dict(
        raw_retention_days=7,
        downsample_10s_retention_days=30,
        downsample_1m_retention_days=180,
        downsample_5m_retention_days=365,
        spread_events_retention_days=None,
        partition_ahead_days=2,
        maintenance_interval_hours=24,
    )
    defaults.update(overrides)
    return RetentionConfig(**defaults)


class FakeResult:
    def __init__(self, rowcount=0, scalar=0):
        self.rowcount = rowcount
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar


class FakeSession:
    def __init__(self, execute_result=None):
        self._execute_result = execute_result or FakeResult()
        self.executed_sql: list[str] = []

    async def execute(self, stmt, params=None):
        self.executed_sql.append(str(stmt))
        return self._execute_result

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def make_manager(config=None, session=None):
    session = session or FakeSession()

    def session_factory():
        return session

    partition_manager = AsyncMock()
    partition_manager.ensure_partitions.return_value = ["quotes_1s_20260716"]
    partition_manager.drop_old_partitions.return_value = []
    downsampler = AsyncMock()
    downsampler.run.return_value = {"quotes_10s": 3, "quotes_1m": 1, "quotes_5m": 0}

    manager = RetentionManager(
        session_factory,
        config or make_config(),
        partition_manager=partition_manager,
        downsampler=downsampler,
    )
    return manager, partition_manager, downsampler, session


async def test_run_once_orchestrates_all_steps():
    manager, partition_manager, downsampler, _session = make_manager()

    metrics = await manager.run_once(current_ms=1_000_000)

    partition_manager.ensure_partitions.assert_awaited_once()
    partition_manager.drop_old_partitions.assert_awaited_once()
    downsampler.run.assert_awaited_once()
    assert metrics.partitions_created == 1
    assert metrics.downsampled_rows == {"quotes_10s": 3, "quotes_1m": 1, "quotes_5m": 0}
    assert metrics.last_run_at_ms == 1_000_000
    assert metrics.last_error is None


async def test_run_once_uses_now_when_no_timestamp_given():
    manager, *_ = make_manager()
    metrics = await manager.run_once()
    assert metrics.last_run_at_ms is not None and metrics.last_run_at_ms > 0


async def test_run_once_catches_exceptions_and_records_error():
    manager, partition_manager, _downsampler, _session = make_manager()
    partition_manager.ensure_partitions.side_effect = RuntimeError("db exploded")

    metrics = await manager.run_once(current_ms=5000)

    assert metrics.last_error == "RuntimeError: db exploded"
    assert metrics.last_run_at_ms == 5000


async def test_spread_events_not_deleted_when_retention_none():
    session = FakeSession()
    config = make_config(spread_events_retention_days=None)
    manager, *_ = make_manager(config=config, session=session)

    await manager.run_once(current_ms=1_000_000)

    assert not any("spread_events" in sql for sql in session.executed_sql)


async def test_spread_events_deleted_when_retention_set():
    session = FakeSession()
    manager, *_ = make_manager(
        config=make_config(spread_events_retention_days=365), session=session
    )

    await manager.run_once(current_ms=1_000_000)

    assert any("spread_events" in sql for sql in session.executed_sql)


async def test_start_stop_lifecycle():
    manager, *_ = make_manager(config=make_config(maintenance_interval_hours=1))
    await manager.start()
    await manager.stop()  # має скасувати фонову задачу без винятків
