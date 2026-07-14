"""Health endpoints (Фаза 1: стан бірж і кешу; повний набір — Фаза 7)."""

from typing import Any

from fastapi import APIRouter, Request

from app.quote_cache.cache import now_ms

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    state = request.app.state
    settings = state.settings
    drift = state.clock_drift

    exchanges: dict[str, Any] = {}
    for adapter in getattr(state, "adapters", []):
        h = adapter.health_status()
        exchanges[h.exchange.value] = {
            "status": h.status.value,
            "last_message_at_ms": h.last_message_at_ms,
            "message_silence_ms": (
                now_ms() - h.last_message_at_ms if h.last_message_at_ms else None
            ),
            "reconnect_count": h.reconnect_count,
            "subscribed_symbols": h.subscribed_symbols,
        }

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment.value,
        "clock_drift_ms": drift.offset_ms if drift.known else "unknown",
        "clock_drift_source": drift.server,
        "exchanges": exchanges,
        "cached_quotes": state.quote_cache.quote_count(),
        "ws_clients": state.ws_manager.client_count,
    }


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "alive"}
