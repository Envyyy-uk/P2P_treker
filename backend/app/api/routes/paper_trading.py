"""Paper Trading API (Фаза 4, п.5): симуляція арбітражної угоди поверх
переданого стану Order Book (клієнт надсилає рівні bid/ask — цей API не
залежить від live WS-глибини, якої ще немає для всіх бірж). Ніяких
реальних викликів бірж; баланси — in-memory "гральні гроші".
"""

from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.models.enums import Exchange
from app.orderbook.book import OrderBook

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])


class BookLevelIn(BaseModel):
    price: Decimal
    quantity: Decimal


class OrderBookIn(BaseModel):
    bids: list[BookLevelIn] = Field(default_factory=list)
    asks: list[BookLevelIn] = Field(default_factory=list)


class ExecuteRequest(BaseModel):
    symbol: str
    buy_exchange: Exchange
    sell_exchange: Exchange
    quantity: Decimal
    buy_book: OrderBookIn
    sell_book: OrderBookIn
    quote_asset: str = "USDT"
    simulated_ack_latency_ms: int = Field(default=0, ge=0)


class SetBalanceRequest(BaseModel):
    exchange: Exchange
    asset: str
    total: Decimal


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


def _serialize(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: _serialize_value(v) for k, v in payload.items()}


def _build_book(levels: OrderBookIn) -> OrderBook:
    book = OrderBook()
    book.apply_snapshot(
        bids=[(level.price, level.quantity) for level in levels.bids],
        asks=[(level.price, level.quantity) for level in levels.asks],
        sequence=1,
    )
    return book


def _engine(request: Request) -> Any:
    engine = getattr(request.app.state, "paper_trading_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Paper trading engine unavailable")
    return engine


@router.post("/execute")
async def execute_trade(request: Request, body: ExecuteRequest) -> dict[str, Any]:
    engine = _engine(request)
    if body.buy_exchange == body.sell_exchange:
        raise HTTPException(status_code=400, detail="buy_exchange and sell_exchange must differ")
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    result = await engine.execute_arbitrage(
        body.symbol,
        body.buy_exchange,
        _build_book(body.buy_book),
        body.sell_exchange,
        _build_book(body.sell_book),
        body.quantity,
        quote_asset=body.quote_asset,
        simulated_ack_latency_ms=body.simulated_ack_latency_ms,
    )
    return _serialize(
        {
            "buy_order": result.buy_order,
            "sell_order": result.sell_order,
            "matched_quantity": result.matched_quantity,
            "leftover_base_quantity": result.leftover_base_quantity,
            "realized_pnl": result.realized_pnl,
            "buy_slippage_pct": result.buy_slippage_pct,
            "sell_slippage_pct": result.sell_slippage_pct,
            "net_spread_after_slippage_pct": result.net_spread_after_slippage_pct,
        }
    )


@router.get("/balances")
async def get_balances(request: Request) -> dict[str, Any]:
    balances = getattr(request.app.state, "paper_trading_balances", None)
    if balances is None:
        raise HTTPException(status_code=503, detail="Paper trading engine unavailable")
    return _serialize(
        {
            f"{exchange.value}:{asset}": {
                "total": bal.total,
                "locked": bal.locked,
                "available": bal.available,
            }
            for (exchange, asset), bal in balances.all_balances().items()
        }
    )


@router.post("/balances")
async def set_balance(request: Request, body: SetBalanceRequest) -> dict[str, Any]:
    balances = getattr(request.app.state, "paper_trading_balances", None)
    if balances is None:
        raise HTTPException(status_code=503, detail="Paper trading engine unavailable")
    balances.set_balance(body.exchange, body.asset, body.total)
    return _serialize({"exchange": body.exchange.value, "asset": body.asset, "total": body.total})
