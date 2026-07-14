"""Точка входу Spread Monitor MVP.

Запуск строго в один процес (план, Фаза 1, п.4):
    uvicorn app.main:app --workers 1
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.websocket.manager import ConnectionManager
from app.api.websocket.routes import router as ws_router
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.core.time_sync import ClockDriftResult, check_clock_drift_on_startup
from app.exchanges.base import ExchangeAdapter
from app.exchanges.base_ws import BaseWsAdapter
from app.exchanges.binance.adapter import BinanceAdapter
from app.exchanges.bybit.adapter import BybitAdapter
from app.exchanges.okx.adapter import OKXAdapter
from app.models.enums import Exchange
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import QuoteCache
from app.services.broadcaster import Broadcaster
from app.spread.engine import SpreadEngine

logger = logging.getLogger(__name__)

_ADAPTER_CLASSES: dict[Exchange, type[BaseWsAdapter]] = {
    Exchange.BINANCE: BinanceAdapter,
    Exchange.BYBIT: BybitAdapter,
    Exchange.OKX: OKXAdapter,
}


def build_adapters(settings: Settings, cache: QuoteCache) -> list[ExchangeAdapter]:
    adapters: list[ExchangeAdapter] = []

    def on_quote(quote: NormalizedQuote) -> None:
        cache.update(quote)

    for exchange, cfg in settings.exchanges.items():
        if not cfg.enabled:
            continue
        adapter_cls = _ADAPTER_CLASSES[exchange]
        adapters.append(
            adapter_cls(
                symbols=settings.trading.symbols,
                ws_config=settings.websocket,
                on_quote=on_quote,
                on_status=cache.set_status,
            )
        )
    return adapters


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 1. Конфігурація валідується тут: невалідний конфіг = застосунок не стартує.
    settings: Settings = get_settings()
    setup_logging(
        level=settings.logging.level,
        json_format=settings.logging.json_format,
        mask=settings.logging.mask_secrets,
        environment=settings.environment.value,
    )
    logger.info(
        "Starting %s v%s (env=%s, symbols=%s)",
        settings.app_name,
        settings.app_version,
        settings.environment.value,
        settings.trading.symbols,
    )

    # 2. Перевірка дрейфу системного часу (Фаза 0, п.11).
    drift: ClockDriftResult = await check_clock_drift_on_startup(
        servers=settings.monitoring.ntp_servers,
        max_drift_ms=settings.monitoring.max_clock_drift_ms,
        fail_on_drift=settings.monitoring.fail_on_clock_drift,
        timeout_s=settings.monitoring.ntp_timeout_s,
    )

    # 3. Компоненти Фази 1: adapters -> normalizer -> cache -> engine -> WS push.
    cache = QuoteCache()
    engine = SpreadEngine(cache, settings)
    manager = ConnectionManager(settings.websocket.client_queue_size)
    broadcaster = Broadcaster(engine, manager, settings.websocket)
    adapters = build_adapters(settings, cache) if settings.live_adapters_enabled else []

    app.state.settings = settings
    app.state.clock_drift = drift
    app.state.quote_cache = cache
    app.state.spread_engine = engine
    app.state.ws_manager = manager
    app.state.broadcaster = broadcaster
    app.state.adapters = adapters

    for adapter in adapters:
        await adapter.connect()
    await broadcaster.start()

    try:
        yield
    finally:
        # Graceful shutdown (Фаза 1, п.2): зупинити push, закрити всі WS.
        # Флаш черги БД додасться у Фазі 2 сюди ж, з таймаутом
        # settings.websocket.graceful_shutdown_timeout_s.
        await broadcaster.stop()
        results = await asyncio.gather(
            *(adapter.disconnect() for adapter in adapters), return_exceptions=True
        )
        for adapter, result in zip(adapters, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("Adapter %s shutdown error: %s", adapter.exchange.value, result)
        logger.info("Shutdown complete")


app = FastAPI(title="Spread Monitor MVP", lifespan=lifespan)
app.include_router(health_router)
app.include_router(ws_router)
