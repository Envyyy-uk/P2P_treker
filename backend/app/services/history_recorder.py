"""Періодичний запис історії (Фаза 2, п.3–5).

Стратегія збереження — варіант 1+3 з плану:
  - один snapshot котирувань за секунду (`quotes_1s`) для кожної живої
    (exchange, symbol) пари в кеші;
  - закриті spread events (`spread_events`) з детектора порогів.

Обидва потоки йдуть через один DbWriter (bounded queue, batch insert) —
запис ніколи не блокує WS-збір/push.
"""

import asyncio
import logging
from itertools import product

from app.core.config import Settings
from app.database.models import Quote1s, SpreadEvent
from app.database.writer import DbWriter
from app.quote_cache.cache import QuoteCache, now_ms
from app.spread.engine import SpreadEngine
from app.spread.events import SpreadEventTracker

logger = logging.getLogger(__name__)


class HistoryRecorder:
    def __init__(
        self,
        cache: QuoteCache,
        engine: SpreadEngine,
        writer: DbWriter,
        settings: Settings,
        event_tracker: SpreadEventTracker | None = None,
    ) -> None:
        self._cache = cache
        self._engine = engine
        self._writer = writer
        self._settings = settings
        self._events = event_tracker or SpreadEventTracker(settings.trading.spread_threshold)
        self._quote_task: asyncio.Task[None] | None = None
        self._event_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._quote_task is None:
            self._quote_task = asyncio.create_task(self._sample_quotes_loop(), name="quote-sampler")
        if self._event_task is None:
            self._event_task = asyncio.create_task(self._event_loop(), name="spread-event-tracker")

    async def stop(self) -> None:
        for task in (self._quote_task, self._event_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._quote_task = None
        self._event_task = None
        # Graceful shutdown: закрити всі відкриті spread events поточним часом,
        # інакше вони губляться назавжди (ніколи не будуть закриті пізніше).
        for row in self._events.flush_open(now_ms()):
            self._writer.enqueue(SpreadEvent.__tablename__, row)

    def sample_quotes_once(self) -> int:
        """Кладе по одному запису на кожну (exchange, symbol) у чергу writer'а."""
        trading = self._settings.trading
        current = now_ms()
        count = 0
        for exchange, symbol in product(self._settings.exchanges, trading.symbols):
            if not self._settings.exchanges[exchange].enabled:
                continue
            quote = self._cache.get(exchange, trading.market_type, symbol)
            if quote is None:
                continue
            row = {
                "timestamp": current,
                "exchange": quote.exchange.value,
                "symbol": quote.symbol,
                "market_type": quote.market_type.value,
                "bid_price": quote.bid_price,
                "bid_quantity": quote.bid_quantity,
                "ask_price": quote.ask_price,
                "ask_quantity": quote.ask_quantity,
                "exchange_timestamp": quote.exchange_timestamp,
                "received_timestamp": quote.received_timestamp,
                "quote_age_ms": quote.quote_age_ms(current),
            }
            self._writer.enqueue(Quote1s.__tablename__, row)
            count += 1
        return count

    def process_events_once(self) -> list[dict[str, object]]:
        rows = self._engine.compute_all(now_ms())
        closed = self._events.process(rows, now_ms())
        for event in closed:
            self._writer.enqueue(SpreadEvent.__tablename__, event)
        return closed

    async def _sample_quotes_loop(self) -> None:
        interval_s = self._settings.database.quotes_sample_interval_ms / 1000.0
        while True:
            try:
                self.sample_quotes_once()
            except Exception:  # noqa: BLE001 - вибірка не має вбити цикл
                logger.exception("Quote sampling iteration failed")
            await asyncio.sleep(interval_s)

    async def _event_loop(self) -> None:
        # Той самий такт, що й frontend push — досить часто, щоб не пропустити
        # коротких сплесків, але не частіше, ніж рахує движок.
        interval_s = 1.0 / self._settings.websocket.frontend_push_rate_hz
        while True:
            try:
                self.process_events_once()
            except Exception:  # noqa: BLE001
                logger.exception("Spread event tracking iteration failed")
            await asyncio.sleep(interval_s)
