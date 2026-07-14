"""Спільна реалізація надійного WebSocket-адаптера (Фаза 1, п.2).

Покриває: reconnect з exponential backoff, keepalive (ping/pong),
повторну підписку після reconnect, контроль часу останнього повідомлення,
timeout detection, логування disconnect/reconnect, graceful shutdown.
Біржова специфіка (URL, підписка, парсинг) — у підкласах.
"""

import asyncio
import json
import logging
import random
from collections.abc import Callable
from typing import Any

import websockets

from app.core.config import WebSocketConfig
from app.core.symbols import to_native
from app.exchanges.base import AdapterHealth, ConnectionStatus, ExchangeAdapter
from app.models.enums import Exchange
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import now_ms

logger = logging.getLogger(__name__)

# Callback для доставки нормалізованого котирування (Quote Cache + статуси).
QuoteSink = Callable[[NormalizedQuote], None]
StatusSink = Callable[[Exchange, ConnectionStatus], None]


class BaseWsAdapter(ExchangeAdapter):
    exchange: Exchange
    ws_url: str
    # Інтервал прикладного keepalive; None — біржа сама шле ping-фрейми.
    keepalive_interval_s: float | None = None

    def __init__(
        self,
        symbols: list[str],
        ws_config: WebSocketConfig,
        on_quote: QuoteSink,
        on_status: StatusSink,
    ) -> None:
        self._symbols = list(symbols)  # канонічні символи
        self._cfg = ws_config
        self._on_quote = on_quote
        self._on_status = on_status
        self._ws: Any = None
        self._run_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._status = ConnectionStatus.DISCONNECTED
        self._last_message_at_ms: int | None = None
        self._reconnect_count = 0

    # ---- біржова специфіка -------------------------------------------------

    def subscribe_payloads(self, native_symbols: list[str]) -> list[str]:
        """JSON-повідомлення підписки для цієї біржі."""
        raise NotImplementedError

    def keepalive_payload(self) -> str | None:
        return None

    def parse(self, message: dict[str, Any], received_ts_ms: int) -> NormalizedQuote | None:
        """Сире повідомлення -> NormalizedQuote (або None для службових)."""
        raise NotImplementedError

    def on_reconnect(self) -> None:
        """Скидання локального стану (наприклад стакана) перед resubscribe."""

    # ---- життєвий цикл -----------------------------------------------------

    async def connect(self) -> None:
        if self._run_task is not None:
            return
        self._stopping = False
        self._run_task = asyncio.create_task(self._run(), name=f"ws-{self.exchange.value}")

    async def disconnect(self) -> None:
        """Graceful shutdown: зупинити цикл і коректно закрити WS."""
        self._stopping = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - закриття не має валити shutdown
                logger.debug("%s: error while closing ws", self.exchange.value, exc_info=True)
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - помилки при зупинці лише логуються
                logger.debug("%s: error during shutdown", self.exchange.value, exc_info=True)
            self._run_task = None
        self._set_status(ConnectionStatus.DISCONNECTED)

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = sorted(set(self._symbols) | set(symbols))
        if self._ws is not None:
            await self._send_subscriptions(self._ws, symbols)

    async def unsubscribe(self, symbols: list[str]) -> None:
        self._symbols = [s for s in self._symbols if s not in set(symbols)]
        # Просте рішення MVP: перепідключення застосує новий список підписок.

    async def handle_message(self, message: dict[str, Any]) -> None:
        received = now_ms()
        self._last_message_at_ms = received
        try:
            quote = self.parse(message, received)
        except Exception:  # noqa: BLE001 - одне биті повідомлення не валить адаптер
            logger.exception("%s: failed to parse message", self.exchange.value)
            return
        if quote is not None:
            self._on_quote(quote)

    def health_status(self) -> AdapterHealth:
        return AdapterHealth(
            exchange=self.exchange,
            status=self._status,
            last_message_at_ms=self._last_message_at_ms,
            reconnect_count=self._reconnect_count,
            subscribed_symbols=list(self._symbols),
        )

    # ---- внутрішнє ----------------------------------------------------------

    def _set_status(self, status: ConnectionStatus) -> None:
        self._status = status
        self._on_status(self.exchange, status)

    async def _send_subscriptions(self, ws: Any, symbols: list[str]) -> None:
        native = [to_native(s, self.exchange) for s in symbols]
        for payload in self.subscribe_payloads(native):
            await ws.send(payload)

    async def _run(self) -> None:
        delay = self._cfg.reconnect_initial_delay_s
        while not self._stopping:
            try:
                self._set_status(
                    ConnectionStatus.RECONNECTING
                    if self._reconnect_count
                    else ConnectionStatus.CONNECTING
                )
                async with websockets.connect(self.ws_url, ping_interval=20) as ws:
                    self._ws = ws
                    self.on_reconnect()
                    await self._send_subscriptions(ws, self._symbols)
                    self._set_status(ConnectionStatus.CONNECTED)
                    logger.info("%s: connected, subscribed %s", self.exchange.value, self._symbols)
                    delay = self._cfg.reconnect_initial_delay_s  # успіх скидає backoff
                    await self._recv_loop(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - будь-який збій -> reconnect
                if self._stopping:
                    break
                logger.warning(
                    "%s: connection lost (%s: %s); reconnect in %.1fs",
                    self.exchange.value,
                    type(exc).__name__,
                    exc,
                    delay,
                )
            finally:
                self._ws = None
            if self._stopping:
                break
            self._reconnect_count += 1
            self._set_status(ConnectionStatus.RECONNECTING)
            await asyncio.sleep(delay * (1 + random.random() * 0.2))  # noqa: S311 - джиттер
            delay = min(delay * 2, self._cfg.reconnect_max_delay_s)

    async def _recv_loop(self, ws: Any) -> None:
        keepalive_task: asyncio.Task[None] | None = None
        if self.keepalive_interval_s is not None:
            keepalive_task = asyncio.create_task(self._keepalive(ws))
        try:
            while not self._stopping:
                # Timeout detection: тиша довша за message_timeout_s = мертве
                # з'єднання -> розрив і reconnect.
                raw = await asyncio.wait_for(ws.recv(), timeout=self._cfg.message_timeout_s)
                if isinstance(raw, bytes):
                    raw = raw.decode()
                if raw in ("ping", "pong"):  # OKX шле текстові ping/pong
                    if raw == "ping":
                        await ws.send("pong")
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("%s: non-JSON message: %.100s", self.exchange.value, raw)
                    continue
                await self.handle_message(message)
        finally:
            if keepalive_task is not None:
                keepalive_task.cancel()

    async def _keepalive(self, ws: Any) -> None:
        assert self.keepalive_interval_s is not None
        while True:
            await asyncio.sleep(self.keepalive_interval_s)
            payload = self.keepalive_payload()
            if payload is not None:
                await ws.send(payload)
