"""Capital Model API (Фаза 4.1): моніторинг балансу по біржах, сигнал
ребалансування, перевірка доступності напрямку арбітражу, фіксація
ручного переказу коштів між біржами (не виконує реальний переказ)."""

from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.capital.monitor import record_manual_transfer
from app.models.enums import Exchange

router = APIRouter(prefix="/api/capital", tags=["capital"])


class CheckDirectionRequest(BaseModel):
    symbol: str
    buy_exchange: Exchange
    sell_exchange: Exchange
    quantity: Decimal
    buy_price: Decimal


class TransferRequest(BaseModel):
    asset: str
    from_exchange: Exchange
    to_exchange: Exchange
    amount: Decimal


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _serialize_value(getattr(value, f.name)) for f in fields(value)}
    return value


def _monitor(request: Request) -> Any:
    monitor = getattr(request.app.state, "capital_monitor", None)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Capital monitor unavailable")
    return monitor


def _balances(request: Request) -> Any:
    balances = getattr(request.app.state, "paper_trading_balances", None)
    if balances is None:
        raise HTTPException(status_code=503, detail="Paper trading engine unavailable")
    return balances


@router.get("/status")
async def get_status(request: Request) -> list[dict[str, Any]]:
    monitor = _monitor(request)
    settings = request.app.state.settings
    exchanges = [e for e, cfg in settings.exchanges.items() if cfg.enabled]
    base_assets = sorted({symbol.split("-")[0] for symbol in settings.trading.symbols})
    statuses = monitor.snapshot(exchanges, base_assets)
    return [_serialize_value(status) for status in statuses]


@router.get("/rebalance-signals")
async def get_rebalance_signals(request: Request) -> list[dict[str, Any]]:
    monitor = _monitor(request)
    settings = request.app.state.settings
    exchanges = [e for e, cfg in settings.exchanges.items() if cfg.enabled]
    signals = monitor.rebalance_signals(exchanges)
    return [_serialize_value(signal) for signal in signals]


@router.post("/check-direction")
async def check_direction(request: Request, body: CheckDirectionRequest) -> dict[str, Any]:
    monitor = _monitor(request)
    result = monitor.check_direction(
        body.symbol, body.buy_exchange, body.sell_exchange, body.quantity, body.buy_price
    )
    return _serialize_value(result)  # type: ignore[no-any-return]


@router.post("/transfer")
async def transfer(request: Request, body: TransferRequest) -> dict[str, Any]:
    balances = _balances(request)
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if body.from_exchange == body.to_exchange:
        raise HTTPException(status_code=400, detail="from_exchange and to_exchange must differ")
    success = record_manual_transfer(
        balances, body.asset, body.from_exchange, body.to_exchange, body.amount
    )
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"insufficient available {body.asset} on {body.from_exchange.value}",
        )
    return {
        "asset": body.asset,
        "from_exchange": body.from_exchange.value,
        "to_exchange": body.to_exchange.value,
        "amount": str(body.amount),
    }
