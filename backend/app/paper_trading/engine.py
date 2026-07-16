"""Paper Trading Engine (Фаза 4, п.5): симуляція арбітражної угоди —
два ордери (купівля на одній біржі, продаж на іншій) поверх реального
Order Book, з VWAP/slippage (Фаза 4, п.2–3) і торговими обмеженнями
(Фаза 4, п.4). Ніяких реальних викликів бірж — усе в пам'яті.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.core.config import PaperTradingConfig
from app.models.enums import Exchange
from app.orderbook.book import OrderBook
from app.orderbook.vwap import buy_slippage_pct, compute_vwap, sell_slippage_pct
from app.paper_trading.balance import BalanceManager
from app.paper_trading.rules import SymbolRules, validate_order
from app.quote_cache.cache import now_ms
from app.spread import formulas

_ZERO = Decimal("0")


class OrderStatus(StrEnum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"


@dataclass
class PaperOrder:
    id: str
    exchange: Exchange
    symbol: str
    side: str  # "buy" | "sell"
    requested_quantity: Decimal
    reference_price: Decimal  # top-of-book у момент прийому ордера
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: Decimal = _ZERO
    avg_fill_price: Decimal | None = None
    fee_paid: Decimal = _ZERO
    rejection_reason: str | None = None
    created_at_ms: int = field(default_factory=now_ms)
    updated_at_ms: int = field(default_factory=now_ms)


@dataclass
class ArbitrageTradeResult:
    buy_order: PaperOrder
    sell_order: PaperOrder
    matched_quantity: Decimal  # min(buy.filled, sell.filled) — реально закрита позиція
    leftover_base_quantity: Decimal  # куплено, але не продано (неявний ризик, не оцінюється)
    realized_pnl: Decimal | None
    buy_slippage_pct: Decimal | None
    sell_slippage_pct: Decimal | None
    net_spread_after_slippage_pct: Decimal | None


def _split_symbol(symbol: str) -> tuple[str, str]:
    base, _, quote = symbol.partition("-")
    return base, quote


class RateLimiter:
    """Фіксоване вікно в 1с — проста симуляція rate limit біржі (план,
    Фаза 4, п.4). Не претендує на точну відповідність алгоритму
    конкретної біржі (token bucket, sliding window тощо)."""

    def __init__(self, max_per_second: int) -> None:
        self._max = max_per_second
        self._window: int | None = None
        self._count = 0

    def allow(self, now_ms_value: int) -> bool:
        window = now_ms_value // 1000
        if window != self._window:
            self._window = window
            self._count = 0
        if self._count >= self._max:
            return False
        self._count += 1
        return True


class PaperTradingEngine:
    def __init__(
        self,
        config: PaperTradingConfig,
        balances: BalanceManager,
        fees: dict[Exchange, Decimal],
    ) -> None:
        self._config = config
        self._balances = balances
        self._fees = fees
        self._rate_limiters: dict[Exchange, RateLimiter] = {}

    def _rate_limiter(self, exchange: Exchange) -> RateLimiter:
        return self._rate_limiters.setdefault(
            exchange, RateLimiter(self._config.rate_limit_orders_per_second)
        )

    def cancel_order(
        self, order: PaperOrder, reserved_asset: str, reserved_amount: Decimal
    ) -> PaperOrder:
        """Скасовує NEW/PARTIALLY_FILLED ордер, звільняє залишок резерву."""
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            return order
        self._balances.release(order.exchange, reserved_asset, reserved_amount)
        order.status = OrderStatus.CANCELED
        order.updated_at_ms = now_ms()
        return order

    async def execute_arbitrage(
        self,
        symbol: str,
        buy_exchange: Exchange,
        buy_book: OrderBook,
        sell_exchange: Exchange,
        sell_book: OrderBook,
        quantity: Decimal,
        quote_asset: str = "USDT",
        simulated_ack_latency_ms: int = 0,
    ) -> ArbitrageTradeResult:
        """Симулює повний цикл: buy leg -> затримка -> sell leg (кількістю,
        що реально купилась, а не заявленою — часткове виконання buy leg
        природно обмежує sell leg)."""
        base_asset, _ = _split_symbol(symbol)
        rules = self._config.rules_for(symbol).to_rules()

        buy_order = self._place_leg(
            symbol,
            buy_exchange,
            "buy",
            quantity,
            buy_book,
            rules,
            quote_asset,
            simulated_ack_latency_ms,
        )

        if buy_order.filled_quantity <= 0:
            sell_order = PaperOrder(
                id=str(uuid.uuid4()),
                exchange=sell_exchange,
                symbol=symbol,
                side="sell",
                requested_quantity=_ZERO,
                reference_price=_ZERO,
                status=OrderStatus.CANCELED,
                rejection_reason="buy leg did not fill",
            )
            return ArbitrageTradeResult(buy_order, sell_order, _ZERO, _ZERO, None, None, None, None)

        if self._config.inter_order_delay_ms > 0:
            await asyncio.sleep(self._config.inter_order_delay_ms / 1000)

        sell_order = self._place_leg(
            symbol,
            sell_exchange,
            "sell",
            buy_order.filled_quantity,
            sell_book,
            rules,
            base_asset,
            simulated_ack_latency_ms,
        )

        return self._settle(buy_order, sell_order, buy_book, sell_book, rules)

    def _place_leg(
        self,
        symbol: str,
        exchange: Exchange,
        side: str,
        quantity: Decimal,
        book: OrderBook,
        rules: SymbolRules,
        reserve_asset: str,
        simulated_ack_latency_ms: int,
    ) -> PaperOrder:
        order_id = str(uuid.uuid4())
        top = book.best_ask() if side == "buy" else book.best_bid()
        reference_price = top.price if top is not None else _ZERO
        order = PaperOrder(
            id=order_id,
            exchange=exchange,
            symbol=symbol,
            side=side,
            requested_quantity=quantity,
            reference_price=reference_price,
        )

        if simulated_ack_latency_ms > self._config.order_timeout_ms:
            order.status = OrderStatus.EXPIRED
            order.rejection_reason = (
                f"ack latency {simulated_ack_latency_ms}ms exceeded timeout "
                f"{self._config.order_timeout_ms}ms"
            )
            return order

        if top is None:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "no liquidity in order book"
            return order

        validation = validate_order(quantity, top.price, rules)
        if not validation.valid:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "; ".join(validation.violations)
            return order

        if not self._rate_limiter(exchange).allow(now_ms()):
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "rate limit exceeded"
            return order

        reserve_amount = quantity * top.price if side == "buy" else quantity
        if not self._balances.reserve(exchange, reserve_asset, reserve_amount):
            order.status = OrderStatus.REJECTED
            order.rejection_reason = (
                f"insufficient available balance for {reserve_asset} on {exchange.value}"
            )
            return order

        levels = book.asks_sorted() if side == "buy" else book.bids_sorted()
        vwap = compute_vwap(levels, quantity)
        if vwap.vwap_price is None:
            self._balances.release(exchange, reserve_asset, reserve_amount)
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "no fillable depth"
            return order

        fee_rate = self._fees.get(exchange, _ZERO)
        order.filled_quantity = vwap.filled_quantity
        order.avg_fill_price = vwap.vwap_price
        order.fee_paid = vwap.notional * fee_rate
        order.status = OrderStatus.FILLED if vwap.fully_filled else OrderStatus.PARTIALLY_FILLED
        order.updated_at_ms = now_ms()

        actual_amount = vwap.notional if side == "buy" else quantity
        # Резерв міг перевищувати фактично використане (часткове виконання) —
        # settle звільняє різницю автоматично.
        self._balances.settle(exchange, reserve_asset, reserve_amount, actual_amount)
        return order

    def _settle(
        self,
        buy_order: PaperOrder,
        sell_order: PaperOrder,
        buy_book: OrderBook,
        sell_book: OrderBook,
        rules: SymbolRules,
    ) -> ArbitrageTradeResult:
        matched = min(buy_order.filled_quantity, sell_order.filled_quantity)
        leftover = buy_order.filled_quantity - matched

        if sell_order.filled_quantity > 0:
            quote_asset = _split_symbol(buy_order.symbol)[1]
            sell_notional = matched * (sell_order.avg_fill_price or _ZERO)
            self._balances.credit(sell_order.exchange, quote_asset, sell_notional)

        realized_pnl = None
        buy_slip = None
        sell_slip = None
        net_after_slippage = None
        if matched > 0 and buy_order.avg_fill_price and sell_order.avg_fill_price:
            buy_fee_rate = self._fees.get(buy_order.exchange, _ZERO)
            sell_fee_rate = self._fees.get(sell_order.exchange, _ZERO)
            cost = matched * buy_order.avg_fill_price * (1 + buy_fee_rate)
            proceeds = matched * sell_order.avg_fill_price * (1 - sell_fee_rate)
            realized_pnl = proceeds - cost

            top_ask = buy_book.best_ask()
            top_bid = sell_book.best_bid()
            if top_ask is not None:
                buy_slip = buy_slippage_pct(top_ask.price, buy_order.avg_fill_price)
            if top_bid is not None:
                sell_slip = sell_slippage_pct(top_bid.price, sell_order.avg_fill_price)
            net = formulas.net_spread(
                buy_order.avg_fill_price, sell_order.avg_fill_price, buy_fee_rate, sell_fee_rate
            )
            net_after_slippage = net * 100

        return ArbitrageTradeResult(
            buy_order=buy_order,
            sell_order=sell_order,
            matched_quantity=matched,
            leftover_base_quantity=leftover,
            realized_pnl=realized_pnl,
            buy_slippage_pct=buy_slip,
            sell_slippage_pct=sell_slip,
            net_spread_after_slippage_pct=net_after_slippage,
        )
