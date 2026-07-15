"""Точка входу Spread Monitor MVP.

Запуск строго в один процес (план, Фаза 1, п.4):
    uvicorn app.main:app --workers 1
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.routes.health import router as health_router
from app.api.websocket.manager import ConnectionManager
from app.api.websocket.routes import router as ws_router
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.core.time_sync import ClockDriftResult, check_clock_drift_on_startup
from app.database.partitioning import PartitionManager
from app.database.session import build_engine, build_session_factory, check_database
from app.database.writer import DbWriter
from app.exchanges.base import ExchangeAdapter
from app.exchanges.base_ws import BaseWsAdapter
from app.exchanges.binance.adapter import BinanceAdapter
from app.exchanges.bybit.adapter import BybitAdapter
from app.exchanges.okx.adapter import OKXAdapter
from app.models.enums import Exchange
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import QuoteCache
from app.repositories.market_data import MarketDataRepository
from app.services.broadcaster import Broadcaster
from app.services.downsampler import Downsampler
from app.services.history_recorder import HistoryRecorder
from app.services.retention_manager import RetentionManager
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


@dataclass
class DbHandles:
    """Спільні компоненти БД, потрібні і writer'у, і retention manager'у."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    writer: DbWriter


async def build_db_handles(settings: Settings) -> DbHandles | None:
    """Фаза 2: DB writer з реальним engine. None, якщо БД вимкнена в конфізі
    або недоступна при старті — збір ринкових даних не блокується відсутністю
    БД, історія просто тимчасово не пишеться (критична помилка в логах)."""
    if not settings.database.enabled:
        logger.info("Database disabled by config; history will not be recorded")
        return None
    engine = build_engine(settings.database)
    if not await check_database(engine):
        await engine.dispose()
        return None
    session_factory = build_session_factory(engine)
    repository = MarketDataRepository(session_factory)
    writer = DbWriter(flush=repository.bulk_insert, config=settings.database)
    return DbHandles(engine=engine, session_factory=session_factory, writer=writer)


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

    # 4. Компоненти Фази 2: bounded async queue -> batch insert -> PostgreSQL.
    db = await build_db_handles(settings)
    writer = db.writer if db is not None else None
    recorder = HistoryRecorder(cache, engine, writer, settings) if writer is not None else None

    # 5. Фаза 2.1: партиції, downsampling, retention — той самий connection pool.
    retention: RetentionManager | None = None
    if db is not None and settings.retention.enabled:
        retention = RetentionManager(
            db.session_factory,
            settings.retention,
            partition_manager=PartitionManager(db.session_factory),
            downsampler=Downsampler(db.session_factory),
        )

    app.state.settings = settings
    app.state.clock_drift = drift
    app.state.quote_cache = cache
    app.state.spread_engine = engine
    app.state.ws_manager = manager
    app.state.broadcaster = broadcaster
    app.state.adapters = adapters
    app.state.db_writer = writer
    app.state.history_recorder = recorder
    app.state.retention_manager = retention

    for adapter in adapters:
        await adapter.connect()
    await broadcaster.start()
    if writer is not None:
        await writer.start()
    if recorder is not None:
        await recorder.start()
    if retention is not None:
        # Партиції на "сьогодні" мають існувати до першого запису семплера.
        await retention.run_once()
        await retention.start()

    try:
        yield
    finally:
        # Graceful shutdown (Фаза 1, п.2 + Фаза 2 flush): зупинити push,
        # закрити всі WS, дописати чергу БД з таймаутом.
        await broadcaster.stop()
        results = await asyncio.gather(
            *(adapter.disconnect() for adapter in adapters), return_exceptions=True
        )
        for adapter, result in zip(adapters, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("Adapter %s shutdown error: %s", adapter.exchange.value, result)
        if recorder is not None:
            await recorder.stop()
        if writer is not None:
            await writer.stop()
        if retention is not None:
            await retention.stop()
        if db is not None:
            await db.engine.dispose()
        logger.info("Shutdown complete")


app = FastAPI(title="Spread Monitor MVP", lifespan=lifespan)
app.include_router(health_router)
app.include_router(ws_router)
