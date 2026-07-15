"""Downsampling quotes_1s -> quotes_10s / quotes_1m / quotes_5m (Фаза 2.1, п.4).

Кожен рівень агрегується напряму з `quotes_1s` (без каскаду рівень-з-рівня) —
простіше і достатньо для обсягів MVP. Ідемпотентно: UPSERT за унікальним
(exchange, symbol, market_type, bucket_timestamp), тож повторний прогін
того самого вікна не дублює і не спотворює дані.
"""

import logging
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownsampleLevel:
    table: str
    bucket_ms: int


LEVELS: tuple[DownsampleLevel, ...] = (
    DownsampleLevel("quotes_10s", 10_000),
    DownsampleLevel("quotes_1m", 60_000),
    DownsampleLevel("quotes_5m", 300_000),
)

# Safety margin: не агрегувати бакети, які ще можуть отримати нові сирі рядки.
_SAFETY_MARGIN_MS = 5_000

_UPSERT_SQL = """
INSERT INTO {table} (
    bucket_timestamp, exchange, symbol, market_type,
    open_bid, high_bid, low_bid, close_bid,
    open_ask, high_ask, low_ask, close_ask,
    avg_bid, avg_ask, avg_quote_age_ms, sample_count
)
SELECT
    (timestamp / :bucket_ms) * :bucket_ms AS bucket_timestamp,
    exchange, symbol, market_type,
    (array_agg(bid_price ORDER BY timestamp ASC))[1] AS open_bid,
    max(bid_price) AS high_bid,
    min(bid_price) AS low_bid,
    (array_agg(bid_price ORDER BY timestamp DESC))[1] AS close_bid,
    (array_agg(ask_price ORDER BY timestamp ASC))[1] AS open_ask,
    max(ask_price) AS high_ask,
    min(ask_price) AS low_ask,
    (array_agg(ask_price ORDER BY timestamp DESC))[1] AS close_ask,
    avg(bid_price) AS avg_bid,
    avg(ask_price) AS avg_ask,
    avg(quote_age_ms) AS avg_quote_age_ms,
    count(*) AS sample_count
FROM quotes_1s
WHERE timestamp >= :from_ms AND timestamp < :to_ms
GROUP BY bucket_timestamp, exchange, symbol, market_type
ON CONFLICT (exchange, symbol, market_type, bucket_timestamp) DO UPDATE SET
    high_bid = EXCLUDED.high_bid,
    low_bid = EXCLUDED.low_bid,
    close_bid = EXCLUDED.close_bid,
    high_ask = EXCLUDED.high_ask,
    low_ask = EXCLUDED.low_ask,
    close_ask = EXCLUDED.close_ask,
    avg_bid = EXCLUDED.avg_bid,
    avg_ask = EXCLUDED.avg_ask,
    avg_quote_age_ms = EXCLUDED.avg_quote_age_ms,
    sample_count = EXCLUDED.sample_count
"""


class Downsampler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        levels: tuple[DownsampleLevel, ...] = LEVELS,
        lookback_ms: int = 3_600_000,
    ) -> None:
        self._session_factory = session_factory
        self._levels = levels
        self._lookback_ms = lookback_ms

    async def run(self, now_ms: int) -> dict[str, int]:
        """Агрегує завершені бакети за останнє вікно [now-lookback, now-margin).

        UPSERT робить повторний прогін одного й того ж вікна безпечним —
        курсор прогресу не потрібен, що спрощує MVP-реалізацію.
        """
        safe_upper_bound = now_ms - _SAFETY_MARGIN_MS
        from_ms = now_ms - self._lookback_ms
        results: dict[str, int] = {}
        async with self._session_factory() as session:
            for level in self._levels:
                rowcount = await self._run_level(session, level, from_ms, safe_upper_bound)
                results[level.table] = rowcount
            await session.commit()
        return results

    async def _run_level(
        self, session: AsyncSession, level: DownsampleLevel, from_ms: int, to_ms: int
    ) -> int:
        sql = _UPSERT_SQL.format(table=level.table)
        result = await session.execute(
            text(sql),
            {"bucket_ms": level.bucket_ms, "from_ms": from_ms, "to_ms": to_ms},
        )
        return cast("CursorResult[Any]", result).rowcount or 0
