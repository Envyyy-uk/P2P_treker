"""Детектор spread events (Фаза 2 `spread_events` + визначення з Фази 3, п.2).

Подія починається, коли ВАЛІДНИЙ net_spread перетинає поріг знизу вгору,
і закінчується, коли він опускається нижче порогу або дані стають
невалідними (stale/обсяг/розсинхрон). Закрита подія повертається одним
записом: start/max/avg spread, обсяг і прибуток у момент максимуму.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.spread.engine import SpreadRow

_HUNDRED = Decimal("100")

DirectionKey = tuple[str, str, str]  # (symbol, buy_exchange, sell_exchange)


@dataclass
class _OpenEvent:
    start_timestamp: int
    symbol: str
    market_type: str
    buy_exchange: str
    sell_exchange: str
    start_net_spread: Decimal  # частка (не відсотки)
    max_net_spread: Decimal
    spread_sum: Decimal
    samples: int
    peak_quantity: Decimal
    peak_notional: Decimal
    peak_profit: Decimal
    calculation_version: int

    def update(self, net: Decimal, row: SpreadRow) -> None:
        self.samples += 1
        self.spread_sum += net
        if net > self.max_net_spread:
            self.max_net_spread = net
            self.peak_quantity = row.executable_quantity
            self.peak_notional = row.executable_notional
            self.peak_profit = row.expected_net_profit

    def close(self, end_timestamp: int, threshold: Decimal) -> dict[str, Any]:
        return {
            "start_timestamp": self.start_timestamp,
            "end_timestamp": end_timestamp,
            "symbol": self.symbol,
            "market_type": self.market_type,
            "buy_exchange": self.buy_exchange,
            "sell_exchange": self.sell_exchange,
            "start_net_spread": self.start_net_spread,
            "max_net_spread": self.max_net_spread,
            "average_net_spread": self.spread_sum / self.samples,
            "executable_quantity": self.peak_quantity,
            "executable_notional": self.peak_notional,
            "estimated_profit": self.peak_profit,
            "threshold": threshold,
            "calculation_version": self.calculation_version,
        }


class SpreadEventTracker:
    def __init__(self, threshold: Decimal) -> None:
        self._threshold = threshold  # частка, напр. 0.001
        self._open: dict[DirectionKey, _OpenEvent] = {}

    @property
    def open_count(self) -> int:
        return len(self._open)

    def process(self, rows: list[SpreadRow], now_ms: int) -> list[dict[str, Any]]:
        """Оновлює стан за поточним зрізом; повертає закриті події."""
        closed: list[dict[str, Any]] = []
        seen: set[DirectionKey] = set()
        for row in rows:
            key = (row.symbol, row.buy_exchange.value, row.sell_exchange.value)
            seen.add(key)
            net = row.net_spread_pct / _HUNDRED  # назад у частку
            active = row.valid and net >= self._threshold
            event = self._open.get(key)
            if event is None:
                if active:  # перетин порогу знизу вгору — початок події
                    self._open[key] = _OpenEvent(
                        start_timestamp=now_ms,
                        symbol=row.symbol,
                        market_type=row.market_type.value,
                        buy_exchange=row.buy_exchange.value,
                        sell_exchange=row.sell_exchange.value,
                        start_net_spread=net,
                        max_net_spread=net,
                        spread_sum=net,
                        samples=1,
                        peak_quantity=row.executable_quantity,
                        peak_notional=row.executable_notional,
                        peak_profit=row.expected_net_profit,
                        calculation_version=row.calculation_version,
                    )
            elif active:
                event.update(net, row)
            else:  # спред упав нижче порогу або дані невалідні — кінець події
                closed.append(event.close(now_ms, self._threshold))
                del self._open[key]
        # Напрямок зник зі зрізу (біржа відвалилась) — теж закриваємо.
        for key in [k for k in self._open if k not in seen]:
            closed.append(self._open.pop(key).close(now_ms, self._threshold))
        return closed

    def flush_open(self, now_ms: int) -> list[dict[str, Any]]:
        """Graceful shutdown: закрити всі відкриті події поточним часом."""
        closed = [event.close(now_ms, self._threshold) for event in self._open.values()]
        self._open.clear()
        return closed
