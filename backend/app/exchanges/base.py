"""Єдиний інтерфейс Exchange Adapter (Фаза 1, п.1; визначений у Фазі 0.3).

Конкретні реалізації (Binance/Bybit/OKX) — Фаза 1.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.models.enums import Exchange


class ConnectionStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class AdapterHealth:
    exchange: Exchange
    status: ConnectionStatus
    last_message_at_ms: int | None = None
    reconnect_count: int = 0
    subscribed_symbols: list[str] = field(default_factory=list)


class ExchangeAdapter(ABC):
    """Базовий клас WebSocket-адаптера біржі.

    Вимоги до реалізацій (Фаза 1, п.2): reconnect з exponential backoff,
    heartbeat/ping-pong, повторна підписка після reconnect, timeout
    detection, sequence check, snapshot/delta, graceful shutdown
    (закрити WS і дочекатись флашу черги перед виходом).
    """

    exchange: Exchange

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Graceful shutdown: коректно закрити WS-з'єднання."""

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Підписка за канонічними символами (мапінг у нативні — всередині)."""

    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None: ...

    @abstractmethod
    async def handle_message(self, message: dict[str, Any]) -> None:
        """Обробка сирого повідомлення біржі -> NormalizedQuote у Quote Cache."""

    @abstractmethod
    def health_status(self) -> AdapterHealth: ...
