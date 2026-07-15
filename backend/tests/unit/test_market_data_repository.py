"""MarketDataRepository.bulk_insert: групування по таблицях, одна транзакція."""

from contextlib import asynccontextmanager

from app.database.models import Quote1s, SpreadEvent
from app.repositories.market_data import MarketDataRepository


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[tuple[str, list[dict]]] = []
        self.begin_called = False

    @asynccontextmanager
    async def begin(self):
        self.begin_called = True
        yield

    async def execute(self, stmt, params):
        self.executed.append((stmt.table.name, params))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def test_bulk_insert_groups_rows_by_table():
    session = FakeSession()

    def session_factory():
        return session

    repo = MarketDataRepository(session_factory)  # type: ignore[arg-type]
    await repo.bulk_insert(
        {
            Quote1s.__tablename__: [{"symbol": "BTC-USDT"}, {"symbol": "ETH-USDT"}],
            SpreadEvent.__tablename__: [{"symbol": "BTC-USDT"}],
        }
    )

    assert session.begin_called
    tables_written = {name for name, _ in session.executed}
    assert tables_written == {"quotes_1s", "spread_events"}
    quotes_call = next(rows for name, rows in session.executed if name == "quotes_1s")
    assert len(quotes_call) == 2


async def test_bulk_insert_skips_empty_table_lists():
    session = FakeSession()
    repo = MarketDataRepository(lambda: session)  # type: ignore[arg-type]
    await repo.bulk_insert({Quote1s.__tablename__: []})
    assert session.executed == []
