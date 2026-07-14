"""Health endpoints (мінімум для Фази 0; повний набір — Фаза 7)."""

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    drift = request.app.state.clock_drift
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment.value,
        "clock_drift_ms": drift.offset_ms if drift.known else "unknown",
        "clock_drift_source": drift.server,
        # Фаза 1 додасть: стан кожної біржі, час останнього повідомлення,
        # розмір черги, dropped records, стан БД.
    }


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "alive"}
