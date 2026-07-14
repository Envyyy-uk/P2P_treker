"""Точка входу Spread Monitor MVP.

Запуск строго в один процес (план, Фаза 1, п.4):
    uvicorn app.main:app --workers 1
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.core.time_sync import ClockDriftResult, check_clock_drift_on_startup

logger = logging.getLogger(__name__)


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
    app.state.settings = settings
    app.state.clock_drift = drift

    # 3. Фаза 1 додасть сюди: запуск exchange adapters, quote cache,
    #    spread engine і graceful shutdown (закриття WS + флаш черги).
    yield
    logger.info("Shutdown complete")


app = FastAPI(title="Spread Monitor MVP", lifespan=lifespan)
app.include_router(health_router)
