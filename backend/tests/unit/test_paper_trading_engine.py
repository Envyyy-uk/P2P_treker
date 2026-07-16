"""PaperTradingEngine: повний цикл арбітражної угоди (Фаза 4, п.5) —
два ордери, VWAP/slippage, часткове виконання, відхилення, timeout,
скасування, комісії, PnL. Усе в пам'яті, без мережі/БД."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.core.config import PaperTradingConfig, SymbolRulesConfig
from app.models.enums import Exchange
from app.orderbook.book import OrderBook
from app.paper_trading.balance import BalanceManager
from app.paper_trading.engine import OrderStatus, PaperTradingEngine

D = Decimal


def make_book(bids, asks, sequence=1) -> OrderBook:
    book = OrderBook()
    book.apply_snapshot(
        bids=[(D(p), D(q)) for p, q in bids],
        asks=[(D(p), D(q)) for p, q in asks],
        sequence=sequence,
    )
    return book


def make_config(**overrides) -> PaperTradingConfig:
    defaults = dict(
        default_rules=SymbolRulesConfig(
            tick_size=D("0.01"),
            step_size=D("0.00001"),
            min_quantity=D("0.0001"),
            min_notional=D("1"),
        ),
        inter_order_delay_ms=0,
        order_timeout_ms=5000,
        rate_limit_orders_per_second=10,
    )
    defaults.update(overrides)
    return PaperTradingConfig(**defaults)


def make_engine(config=None, fees=None, funded=True):
    balances = BalanceManager()
    if funded:
        balances.set_balance(Exchange.BINANCE, "USDT", D("1_000_000"))
        balances.set_balance(Exchange.BYBIT, "BTC", D("1_000_000"))
    fees = fees or {Exchange.BINANCE: D("0.001"), Exchange.BYBIT: D("0.001")}
    return PaperTradingEngine(config or make_config(), balances, fees), balances


class TestSuccessfulArbitrage:
    async def test_both_legs_fill_with_positive_pnl(self):
        engine, _balances = make_engine()
        buy_book = make_book(bids=[("99.9", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("102.1", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )

        assert result.buy_order.status == OrderStatus.FILLED
        assert result.sell_order.status == OrderStatus.FILLED
        assert result.buy_order.avg_fill_price == D("100")
        assert result.sell_order.avg_fill_price == D("102")
        assert result.matched_quantity == D("1")
        assert result.leftover_base_quantity == 0
        assert result.realized_pnl is not None and result.realized_pnl > 0

    async def test_pnl_matches_manual_calculation(self):
        engine, _balances = make_engine(
            fees={Exchange.BINANCE: D("0.001"), Exchange.BYBIT: D("0.002")}
        )
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("2")
        )

        cost = D("2") * D("100") * (D("1") + D("0.001"))
        proceeds = D("2") * D("102") * (D("1") - D("0.002"))
        assert result.realized_pnl == proceeds - cost

    async def test_fees_are_charged_on_notional(self):
        engine, _balances = make_engine(
            fees={Exchange.BINANCE: D("0.01"), Exchange.BYBIT: D("0.01")}
        )
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("101", "10")], asks=[("102", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        assert result.buy_order.fee_paid == D("1") * D("100") * D("0.01")
        assert result.sell_order.fee_paid == D("1") * D("101") * D("0.01")


class TestDifferentFillPricesViaVwap:
    async def test_multi_level_book_gives_vwap_different_from_top(self):
        engine, _balances = make_engine()
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "1"), ("100.5", "1")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("2")
        )
        assert result.buy_order.avg_fill_price == D("100.25")  # (1*100 + 1*100.5) / 2
        assert result.buy_slippage_pct is not None and result.buy_slippage_pct > 0


class TestPartialFill:
    async def test_buy_leg_partial_fill_limits_sell_leg_quantity(self):
        engine, _balances = make_engine()
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "0.5")])  # only 0.5 available
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        assert result.buy_order.status == OrderStatus.PARTIALLY_FILLED
        assert result.buy_order.filled_quantity == D("0.5")
        assert result.sell_order.requested_quantity == D("0.5")
        assert result.sell_order.status == OrderStatus.FILLED
        assert result.matched_quantity == D("0.5")

    async def test_sell_leg_partial_leaves_leftover(self):
        engine, _balances = make_engine()
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "1")])
        sell_book = make_book(
            bids=[("102", "0.4")], asks=[("103", "10")]
        )  # not enough depth to sell all

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        assert result.buy_order.filled_quantity == D("1")
        assert result.sell_order.filled_quantity == D("0.4")
        assert result.matched_quantity == D("0.4")
        assert result.leftover_base_quantity == D("0.6")


class TestRejections:
    async def test_no_liquidity_rejects_buy_leg(self):
        engine, _balances = make_engine()
        buy_book = OrderBook()  # empty, no snapshot applied
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        assert result.buy_order.status == OrderStatus.REJECTED
        assert "liquidity" in result.buy_order.rejection_reason
        assert result.sell_order.status == OrderStatus.CANCELED
        assert result.realized_pnl is None

    async def test_rule_violation_rejects_order(self):
        config = make_config(
            default_rules=SymbolRulesConfig(
                tick_size=D("0.01"),
                step_size=D("0.00001"),
                min_quantity=D("5"),
                min_notional=D("1"),
            )
        )
        engine, _balances = make_engine(config=config)
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        assert result.buy_order.status == OrderStatus.REJECTED
        assert "min_quantity" in result.buy_order.rejection_reason

    async def test_insufficient_balance_rejects_order(self):
        engine, balances = make_engine(funded=False)
        balances.set_balance(Exchange.BINANCE, "USDT", D("1"))  # not enough for 1 BTC @ 100
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        assert result.buy_order.status == OrderStatus.REJECTED
        assert "balance" in result.buy_order.rejection_reason

    async def test_rate_limit_exceeded_rejects_order(self):
        config = make_config(rate_limit_orders_per_second=1)
        engine, _balances = make_engine(config=config)
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        first = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        second = await engine.execute_arbitrage(
            "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
        )
        assert first.buy_order.status == OrderStatus.FILLED
        assert second.buy_order.status == OrderStatus.REJECTED
        assert "rate limit" in second.buy_order.rejection_reason


class TestTimeout:
    async def test_ack_latency_over_timeout_expires_order(self):
        config = make_config(order_timeout_ms=100)
        engine, _balances = make_engine(config=config)
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        result = await engine.execute_arbitrage(
            "BTC-USDT",
            Exchange.BINANCE,
            buy_book,
            Exchange.BYBIT,
            sell_book,
            D("1"),
            simulated_ack_latency_ms=500,
        )
        assert result.buy_order.status == OrderStatus.EXPIRED
        assert "timeout" in result.buy_order.rejection_reason


class TestInterOrderDelay:
    async def test_delay_between_legs_is_awaited(self):
        config = make_config(inter_order_delay_ms=250)
        engine, _balances = make_engine(config=config)
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        with patch("app.paper_trading.engine.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await engine.execute_arbitrage(
                "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
            )
        mock_sleep.assert_awaited_once_with(0.25)

    async def test_no_delay_when_buy_leg_rejected(self):
        config = make_config(inter_order_delay_ms=250)
        engine, _balances = make_engine(config=config, funded=False)
        buy_book = make_book(bids=[("99", "10")], asks=[("100", "10")])
        sell_book = make_book(bids=[("102", "10")], asks=[("103", "10")])

        with patch("app.paper_trading.engine.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await engine.execute_arbitrage(
                "BTC-USDT", Exchange.BINANCE, buy_book, Exchange.BYBIT, sell_book, D("1")
            )
        mock_sleep.assert_not_awaited()


class TestCancelOrder:
    async def test_cancel_releases_reservation(self):
        engine, balances = make_engine()
        balances.set_balance(Exchange.BINANCE, "USDT", D("1000"))
        balances.reserve(Exchange.BINANCE, "USDT", D("500"))
        from app.paper_trading.engine import PaperOrder

        order = PaperOrder(
            id="x",
            exchange=Exchange.BINANCE,
            symbol="BTC-USDT",
            side="buy",
            requested_quantity=D("5"),
            reference_price=D("100"),
        )
        engine.cancel_order(order, "USDT", D("500"))
        assert order.status == OrderStatus.CANCELED
        assert balances.available(Exchange.BINANCE, "USDT") == D("1000")  # reservation released

    async def test_cancel_is_noop_for_terminal_states(self):
        engine, balances = make_engine()
        from app.paper_trading.engine import PaperOrder

        order = PaperOrder(
            id="x",
            exchange=Exchange.BINANCE,
            symbol="BTC-USDT",
            side="buy",
            requested_quantity=D("1"),
            reference_price=D("100"),
            status=OrderStatus.FILLED,
        )
        engine.cancel_order(order, "USDT", D("100"))
        assert order.status == OrderStatus.FILLED  # unchanged
