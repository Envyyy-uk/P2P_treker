"""PartitionManager: генерація DDL для денних партицій (без реальної БД)."""

from app.database.partitioning import PartitionManager

_DAY_MS = 24 * 60 * 60 * 1000
NOW = 1_784_246_400_000  # 2026-07-16T12:00:00Z


class FakeResult:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self._rows = rows or []

    def fetchall(self):
        return self._rows


class FakeSession:
    def __init__(self, existing_partition_names: list[str] | None = None) -> None:
        self.executed_sql: list[str] = []
        self._existing = existing_partition_names or []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed_sql.append(sql)
        if "pg_inherits" in sql:
            return FakeResult([(name,) for name in self._existing])
        return FakeResult()

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def make_manager(session: FakeSession) -> PartitionManager:
    return PartitionManager(lambda: session)


async def test_ensure_partitions_creates_expected_names():
    session = FakeSession()
    manager = make_manager(session)

    created = await manager.ensure_partitions(NOW, ahead_days=2, behind_days=1)

    assert created == [
        "quotes_1s_20260716",
        "quotes_1s_20260717",
        "quotes_1s_20260718",
        "quotes_1s_20260719",
    ]
    assert all("CREATE TABLE IF NOT EXISTS" in sql for sql in session.executed_sql)


async def test_ensure_partitions_inlines_bounds_as_integers():
    session = FakeSession()
    manager = make_manager(session)

    await manager.ensure_partitions(NOW, ahead_days=0, behind_days=0)

    (sql,) = session.executed_sql
    assert "FOR VALUES FROM (1784246400000) TO (1784332800000)" in sql


async def test_existing_partitions_filters_by_prefix_query():
    session = FakeSession(existing_partition_names=["quotes_1s_default", "quotes_1s_20260716"])
    manager = make_manager(session)

    names = await manager.existing_partitions()

    assert names == ["quotes_1s_default", "quotes_1s_20260716"]
    assert any("pg_inherits" in sql for sql in session.executed_sql)


async def test_drop_old_partitions_skips_default_partition():
    session = FakeSession(existing_partition_names=["quotes_1s_default", "quotes_1s_20260601"])
    manager = make_manager(session)

    dropped = await manager.drop_old_partitions(NOW, retention_days=7)

    assert dropped == ["quotes_1s_20260601"]
    assert not any("quotes_1s_default" in sql for sql in session.executed_sql if "DROP" in sql)


async def test_drop_old_partitions_keeps_recent_ones():
    session = FakeSession(existing_partition_names=["quotes_1s_20260716"])
    manager = make_manager(session)

    dropped = await manager.drop_old_partitions(NOW, retention_days=7)

    assert dropped == []


async def test_drop_old_partitions_drops_multiple_expired():
    session = FakeSession(
        existing_partition_names=["quotes_1s_20260101", "quotes_1s_20260102", "quotes_1s_20260716"]
    )
    manager = make_manager(session)

    dropped = await manager.drop_old_partitions(NOW, retention_days=7)

    assert set(dropped) == {"quotes_1s_20260101", "quotes_1s_20260102"}
