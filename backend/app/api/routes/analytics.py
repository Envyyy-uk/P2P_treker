"""Analytics API (Фаза 3): історія котирувань/спредів, threshold events,
статистика, експорт. Тільки читання — не впливає на live-моніторинг.
"""

import csv
import io
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.models.enums import Exchange, MarketType
from app.repositories.analytics import choose_interval

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _serialize_value(value: Any) -> Any:
    """Decimal -> str рекурсивно, щоб не втратити точність у JSON (як у WS)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


def _serialize(payload: dict[str, Any]) -> dict[str, Any]:
    """Варіант _serialize_value з точним типом для відповідей-словників."""
    return {k: _serialize_value(v) for k, v in payload.items()}


def _repo(request: Request) -> Any:
    repo = getattr(request.app.state, "analytics_repo", None)
    if repo is None:
        raise HTTPException(
            status_code=503, detail="Analytics unavailable: database is disabled or unreachable"
        )
    return repo


@router.get("/quotes")
async def quote_history(
    request: Request,
    exchange: Exchange,
    symbol: str,
    from_ms: int = Query(..., alias="from"),
    to_ms: int = Query(..., alias="to"),
    market_type: MarketType = MarketType.SPOT,
    interval: str = "auto",
) -> dict[str, Any]:
    if to_ms <= from_ms:
        raise HTTPException(status_code=400, detail="'to' must be greater than 'from'")
    repo = _repo(request)
    settings = request.app.state.settings
    try:
        resolved_interval = choose_interval(
            from_ms, to_ms, settings.analytics.max_chart_points, interval
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await repo.quote_history(
        exchange=exchange,
        symbol=symbol,
        market_type=market_type,
        from_ms=from_ms,
        to_ms=to_ms,
        interval=resolved_interval,
        max_points=settings.analytics.max_chart_points,
    )
    return _serialize(
        {
            "symbol": symbol,
            "exchange": exchange.value,
            "market_type": market_type.value,
            "interval": result.interval,
            "truncated": result.truncated,
            "points": result.points,
        }
    )


@router.get("/spread-history")
async def spread_history(
    request: Request,
    buy_exchange: Exchange,
    sell_exchange: Exchange,
    symbol: str,
    from_ms: int = Query(..., alias="from"),
    to_ms: int = Query(..., alias="to"),
    market_type: MarketType = MarketType.SPOT,
    interval: str = "auto",
) -> dict[str, Any]:
    if to_ms <= from_ms:
        raise HTTPException(status_code=400, detail="'to' must be greater than 'from'")
    if buy_exchange == sell_exchange:
        raise HTTPException(status_code=400, detail="buy_exchange and sell_exchange must differ")
    repo = _repo(request)
    settings = request.app.state.settings
    try:
        resolved_interval = choose_interval(
            from_ms, to_ms, settings.analytics.max_chart_points, interval
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    buy_fee = settings.exchanges[buy_exchange].taker_fee
    sell_fee = settings.exchanges[sell_exchange].taker_fee
    result = await repo.spread_history(
        buy_exchange=buy_exchange,
        sell_exchange=sell_exchange,
        symbol=symbol,
        market_type=market_type,
        from_ms=from_ms,
        to_ms=to_ms,
        interval=resolved_interval,
        max_points=settings.analytics.max_chart_points,
        buy_fee=buy_fee,
        sell_fee=sell_fee,
    )
    return _serialize(
        {
            "symbol": symbol,
            "buy_exchange": buy_exchange.value,
            "sell_exchange": sell_exchange.value,
            "market_type": market_type.value,
            "interval": result.interval,
            "threshold_pct": settings.trading.spread_threshold * 100,
            "truncated": result.truncated,
            "points": result.points,
        }
    )


def _event_filter_params(
    request: Request,
    symbol: str | None,
    buy_exchange: Exchange | None,
    sell_exchange: Exchange | None,
    market_type: MarketType | None,
    from_ms: int | None,
    to_ms: int | None,
    min_net_spread_pct: Decimal | None,
    min_notional: Decimal | None,
    min_duration_ms: int | None,
) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "symbol": symbol,
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "market_type": market_type,
        "from_ms": from_ms,
        "to_ms": to_ms,
        "min_net_spread_pct": min_net_spread_pct,
        "min_notional": min_notional,
        "min_duration_ms": (
            min_duration_ms
            if min_duration_ms is not None
            else settings.analytics.default_min_event_duration_ms
        ),
    }


@router.get("/spread-events")
async def list_spread_events(
    request: Request,
    symbol: str | None = None,
    buy_exchange: Exchange | None = None,
    sell_exchange: Exchange | None = None,
    market_type: MarketType | None = None,
    from_ms: int | None = Query(None, alias="from"),
    to_ms: int | None = Query(None, alias="to"),
    min_net_spread_pct: Decimal | None = None,
    min_notional: Decimal | None = None,
    min_duration_ms: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1),
) -> dict[str, Any]:
    repo = _repo(request)
    settings = request.app.state.settings
    effective_page_size = min(
        page_size or settings.analytics.default_page_size, settings.analytics.max_page_size
    )
    filters = _event_filter_params(
        request,
        symbol,
        buy_exchange,
        sell_exchange,
        market_type,
        from_ms,
        to_ms,
        min_net_spread_pct,
        min_notional,
        min_duration_ms,
    )
    events, total = await repo.list_spread_events(
        **filters, page=page, page_size=effective_page_size
    )
    return _serialize(
        {
            "page": page,
            "page_size": effective_page_size,
            "total_count": total,
            "events": events,
        }
    )


@router.get("/spread-events/stats")
async def spread_event_stats(
    request: Request,
    symbol: str | None = None,
    buy_exchange: Exchange | None = None,
    sell_exchange: Exchange | None = None,
    market_type: MarketType | None = None,
    from_ms: int | None = Query(None, alias="from"),
    to_ms: int | None = Query(None, alias="to"),
    min_net_spread_pct: Decimal | None = None,
    min_notional: Decimal | None = None,
    min_duration_ms: int | None = None,
) -> dict[str, Any]:
    repo = _repo(request)
    filters = _event_filter_params(
        request,
        symbol,
        buy_exchange,
        sell_exchange,
        market_type,
        from_ms,
        to_ms,
        min_net_spread_pct,
        min_notional,
        min_duration_ms,
    )
    stats = await repo.spread_event_stats(**filters)
    return _serialize(
        {
            "total_count": stats.total_count,
            "qualifying_count": stats.qualifying_count,
            "pct_meeting_min_duration": stats.pct_meeting_min_duration,
            "total_duration_ms": stats.total_duration_ms,
            "average_duration_ms": stats.average_duration_ms,
            "median_duration_ms": stats.median_duration_ms,
            "max_duration_ms": stats.max_duration_ms,
            "average_net_spread_pct": stats.average_net_spread_pct,
            "max_net_spread_pct": stats.max_net_spread_pct,
            "average_executable_quantity": stats.average_executable_quantity,
            "average_estimated_profit": stats.average_estimated_profit,
        }
    )


@router.get("/spread-events/export")
async def export_spread_events(
    request: Request,
    format: str = Query("json", pattern="^(json|csv)$"),
    symbol: str | None = None,
    buy_exchange: Exchange | None = None,
    sell_exchange: Exchange | None = None,
    market_type: MarketType | None = None,
    from_ms: int | None = Query(None, alias="from"),
    to_ms: int | None = Query(None, alias="to"),
    min_net_spread_pct: Decimal | None = None,
    min_notional: Decimal | None = None,
    min_duration_ms: int | None = None,
) -> Any:
    repo = _repo(request)
    filters = _event_filter_params(
        request,
        symbol,
        buy_exchange,
        sell_exchange,
        market_type,
        from_ms,
        to_ms,
        min_net_spread_pct,
        min_notional,
        min_duration_ms,
    )
    rows = await repo.export_spread_events(**filters)

    if format == "json":
        return _serialize_value(rows)

    buffer = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else []
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()})
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=spread_events.csv"},
    )
