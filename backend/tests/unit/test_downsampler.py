"""Downsampler: генерація UPSERT-запитів на кожен рівень (без реальної БД)."""

from app.services.downsampler import LEVELS, DownsampleLevel, Downsampler


class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params):
        sql = str(stmt)
        self.calls.append((sql, params))
        # Повертаємо різну "кількість оновлених рядків" за bucket_ms, щоб
        # перевірити, що результат прив'язаний до правильного рівня.
        return FakeResult(rowcount=params["bucket_ms"] // 1000)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def test_run_executes_all_configured_levels():
    session = FakeSession()

    def session_factory():
        return session

    downsampler = Downsampler(session_factory)
    results = await downsampler.run(now_ms=1_000_000)

    assert set(results) == {"quotes_10s", "quotes_1m", "quotes_5m"}
    assert len(session.calls) == 3


async def test_run_uses_safety_margin_and_lookback():
    session = FakeSession()
    downsampler = Downsampler(lambda: session, lookback_ms=100_000)

    await downsampler.run(now_ms=1_000_000)

    for _sql, params in session.calls:
        assert params["to_ms"] == 1_000_000 - 5_000  # safety margin
        assert params["from_ms"] == 1_000_000 - 100_000


async def test_run_returns_rowcount_per_level():
    session = FakeSession()
    downsampler = Downsampler(lambda: session)

    results = await downsampler.run(now_ms=1_000_000)

    assert results["quotes_10s"] == 10  # 10_000 // 1000
    assert results["quotes_1m"] == 60
    assert results["quotes_5m"] == 300


async def test_custom_levels_override_defaults():
    session = FakeSession()
    custom = (DownsampleLevel("quotes_10s", 10_000),)
    downsampler = Downsampler(lambda: session, levels=custom)

    results = await downsampler.run(now_ms=1_000_000)

    assert set(results) == {"quotes_10s"}
    assert len(session.calls) == 1


def test_default_levels_match_plan_granularities():
    tables = {level.table for level in LEVELS}
    assert tables == {"quotes_10s", "quotes_1m", "quotes_5m"}
