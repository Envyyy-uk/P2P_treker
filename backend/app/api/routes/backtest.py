"""Historical Backtesting API (Фаза 3.1). Read-only симуляція поверх
уже записаної історії — не впливає на live-моніторинг чи будь-які дані."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.backtesting.engine import BacktestParams
from app.models.enums import Exchange, MarketType

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    symbols: list[str]
    from_ms: int = Field(..., alias="from")
    to_ms: int = Field(..., alias="to")
    market_type: MarketType = MarketType.SPOT
    spread_threshold: Decimal | None = None
    min_duration_ms: int = Field(default=0, ge=0)
    min_executable_quantity: Decimal | None = None
    min_executable_notional: Decimal | None = None
    fee_overrides: dict[Exchange, Decimal] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


def _serialize_value(value: Any) -> Any:
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


@router.post("/run")
async def run_backtest(request: Request, body: BacktestRequest) -> dict[str, Any]:
    engine = getattr(request.app.state, "backtest_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503, detail="Backtesting unavailable: database is disabled or unreachable"
        )
    try:
        params = BacktestParams(
            symbols=body.symbols,
            from_ms=body.from_ms,
            to_ms=body.to_ms,
            market_type=body.market_type,
            spread_threshold=body.spread_threshold,
            min_duration_ms=body.min_duration_ms,
            min_executable_quantity=body.min_executable_quantity,
            min_executable_notional=body.min_executable_notional,
            fee_overrides=body.fee_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await engine.run(params)
    return _serialize(
        {
            "symbols": params.symbols,
            "from": params.from_ms,
            "to": params.to_ms,
            "market_type": params.market_type.value,
            "ticks_processed": result.ticks_processed,
            "truncated": result.truncated,
            "total_events": result.total_events,
            "total_simulated_pnl": result.total_simulated_pnl,
            "average_pnl_per_event": result.average_pnl_per_event,
            "events": result.events,
            "disclaimer": result.disclaimer,
        }
    )
