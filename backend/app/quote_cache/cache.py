"""In-memory Quote Cache (Фаза 1, п.4).

Структура: quotes[exchange][market_type][symbol].
Живе в одному процесі FastAPI (--workers 1) — кілька workers мали б
розсинхронізовані копії.
"""

import logging
import time

from app.exchanges.base import ConnectionStatus
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote

logger = logging.getLogger(__name__)


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class QuoteCache:
    def __init__(self) -> None:
        self._quotes: dict[Exchange, dict[MarketType, dict[str, NormalizedQuote]]] = {}
        self._status: dict[Exchange, ConnectionStatus] = {}

    def update(self, quote: NormalizedQuote) -> bool:
        """Кладе котирування в кеш.

        Повертає False (і не оновлює), якщо sequence менший за вже
        збережений — захист від out-of-order повідомлень.
        """
        by_market = self._quotes.setdefault(quote.exchange, {})
        by_symbol = by_market.setdefault(quote.market_type, {})
        current = by_symbol.get(quote.symbol)
        if (
            current is not None
            and current.sequence is not None
            and quote.sequence is not None
            and quote.sequence < current.sequence
        ):
            logger.warning(
                "Out-of-order quote dropped: %s %s seq %s < %s",
                quote.exchange.value,
                quote.symbol,
                quote.sequence,
                current.sequence,
            )
            return False
        by_symbol[quote.symbol] = quote
        return True

    def get(
        self, exchange: Exchange, market_type: MarketType, symbol: str
    ) -> NormalizedQuote | None:
        return self._quotes.get(exchange, {}).get(market_type, {}).get(symbol)

    def snapshot(self, market_type: MarketType, symbol: str) -> dict[Exchange, NormalizedQuote]:
        """Останні котирування символу з усіх бірж (без фільтра freshness —
        stale-логіка застосовується у Spread Engine)."""
        result: dict[Exchange, NormalizedQuote] = {}
        for exchange, by_market in self._quotes.items():
            quote = by_market.get(market_type, {}).get(symbol)
            if quote is not None:
                result[exchange] = quote
        return result

    def set_status(self, exchange: Exchange, status: ConnectionStatus) -> None:
        self._status[exchange] = status

    def get_status(self, exchange: Exchange) -> ConnectionStatus:
        return self._status.get(exchange, ConnectionStatus.DISCONNECTED)

    def quote_count(self) -> int:
        return sum(
            len(by_symbol)
            for by_market in self._quotes.values()
            for by_symbol in by_market.values()
        )
