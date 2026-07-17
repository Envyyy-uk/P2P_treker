"""CapitalMonitor (Фаза 4.1): снепшот балансу по біржах, target allocation,
сигнал ребалансування, перевірка доступності напрямку, ручний переказ."""

from decimal import Decimal

from app.capital.monitor import CapitalMonitor, record_manual_transfer
from app.core.config import CapitalConfig
from app.models.enums import Exchange
from app.paper_trading.balance import BalanceManager

D = Decimal


def _balances(
    binance_usdt: str, bybit_usdt: str, binance_btc: str = "0", bybit_btc: str = "0"
) -> BalanceManager:
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D(binance_usdt))
    manager.set_balance(Exchange.BYBIT, "USDT", D(bybit_usdt))
    manager.set_balance(Exchange.BINANCE, "BTC", D(binance_btc))
    manager.set_balance(Exchange.BYBIT, "BTC", D(bybit_btc))
    return manager


class TestSnapshot:
    def test_actual_pct_reflects_quote_totals(self):
        balances = _balances("6000", "4000")
        monitor = CapitalMonitor(balances, CapitalConfig())
        statuses = monitor.snapshot([Exchange.BINANCE, Exchange.BYBIT], base_assets=["BTC"])
        by_exchange = {s.exchange: s for s in statuses}
        assert by_exchange[Exchange.BINANCE].actual_pct == D("60")
        assert by_exchange[Exchange.BYBIT].actual_pct == D("40")

    def test_target_and_deviation_when_configured(self):
        balances = _balances("6000", "4000")
        config = CapitalConfig(
            target_allocation={Exchange.BINANCE: D("50"), Exchange.BYBIT: D("50")}
        )
        monitor = CapitalMonitor(balances, config)
        statuses = monitor.snapshot([Exchange.BINANCE, Exchange.BYBIT], base_assets=[])
        by_exchange = {s.exchange: s for s in statuses}
        assert by_exchange[Exchange.BINANCE].target_pct == D("50")
        assert by_exchange[Exchange.BINANCE].deviation_pct == D("10")
        assert by_exchange[Exchange.BYBIT].deviation_pct == D("-10")

    def test_target_none_when_not_configured(self):
        balances = _balances("6000", "4000")
        monitor = CapitalMonitor(balances, CapitalConfig())
        statuses = monitor.snapshot([Exchange.BINANCE, Exchange.BYBIT], base_assets=[])
        assert all(s.target_pct is None and s.deviation_pct is None for s in statuses)

    def test_actual_pct_none_when_total_capital_zero(self):
        balances = _balances("0", "0")
        monitor = CapitalMonitor(balances, CapitalConfig())
        statuses = monitor.snapshot([Exchange.BINANCE, Exchange.BYBIT], base_assets=[])
        assert all(s.actual_pct is None for s in statuses)

    def test_base_asset_statuses_included(self):
        balances = _balances("6000", "4000", binance_btc="1.5")
        balances.reserve(Exchange.BINANCE, "BTC", D("0.5"))
        monitor = CapitalMonitor(balances, CapitalConfig())
        statuses = monitor.snapshot([Exchange.BINANCE], base_assets=["BTC"])
        btc_status = statuses[0].base_asset_statuses["BTC"]
        assert btc_status.total == D("1.5")
        assert btc_status.locked == D("0.5")
        assert btc_status.available == D("1")


class TestRebalanceSignals:
    def test_no_signal_when_within_threshold(self):
        balances = _balances("5200", "4800")  # 52/48, threshold default 10%
        config = CapitalConfig(
            target_allocation={Exchange.BINANCE: D("50"), Exchange.BYBIT: D("50")}
        )
        monitor = CapitalMonitor(balances, config)
        signals = monitor.rebalance_signals([Exchange.BINANCE, Exchange.BYBIT])
        assert signals == []

    def test_no_signal_when_target_not_configured(self):
        balances = _balances("9000", "1000")
        monitor = CapitalMonitor(balances, CapitalConfig())
        signals = monitor.rebalance_signals([Exchange.BINANCE, Exchange.BYBIT])
        assert signals == []

    def test_signal_generated_when_deviation_exceeds_threshold(self):
        balances = _balances("8000", "2000")  # 80/20 vs target 50/50
        config = CapitalConfig(
            target_allocation={Exchange.BINANCE: D("50"), Exchange.BYBIT: D("50")}
        )
        monitor = CapitalMonitor(balances, config)
        signals = monitor.rebalance_signals([Exchange.BINANCE, Exchange.BYBIT])
        assert len(signals) == 1
        signal = signals[0]
        assert signal.from_exchange == Exchange.BINANCE
        assert signal.to_exchange == Exchange.BYBIT
        assert signal.amount == D("3000")  # 30% of 10000 total capital
        assert signal.asset == "USDT"

    def test_no_signal_when_total_capital_zero(self):
        balances = _balances("0", "0")
        config = CapitalConfig(
            target_allocation={Exchange.BINANCE: D("50"), Exchange.BYBIT: D("50")}
        )
        monitor = CapitalMonitor(balances, config)
        assert monitor.rebalance_signals([Exchange.BINANCE, Exchange.BYBIT]) == []


class TestCheckDirection:
    def test_available_when_both_legs_have_enough_capital(self):
        balances = _balances("10000", "10000", binance_btc="0", bybit_btc="5")
        monitor = CapitalMonitor(balances, CapitalConfig())
        result = monitor.check_direction(
            "BTC-USDT", Exchange.BINANCE, Exchange.BYBIT, D("1"), D("100")
        )
        assert result.available
        assert result.reason is None

    def test_unavailable_when_quote_balance_insufficient_on_buy_exchange(self):
        balances = _balances("50", "10000", binance_btc="0", bybit_btc="5")
        monitor = CapitalMonitor(balances, CapitalConfig())
        result = monitor.check_direction(
            "BTC-USDT", Exchange.BINANCE, Exchange.BYBIT, D("1"), D("100")
        )
        assert not result.available
        assert "USDT" in result.reason
        assert "binance" in result.reason

    def test_unavailable_when_base_balance_insufficient_on_sell_exchange(self):
        balances = _balances("10000", "10000", binance_btc="0", bybit_btc="0.1")
        monitor = CapitalMonitor(balances, CapitalConfig())
        result = monitor.check_direction(
            "BTC-USDT", Exchange.BINANCE, Exchange.BYBIT, D("1"), D("100")
        )
        assert not result.available
        assert "BTC" in result.reason
        assert "bybit" in result.reason


class TestRecordManualTransfer:
    def test_transfer_moves_funds_between_exchanges(self):
        balances = _balances("10000", "0")
        ok = record_manual_transfer(balances, "USDT", Exchange.BINANCE, Exchange.BYBIT, D("3000"))
        assert ok
        assert balances.available(Exchange.BINANCE, "USDT") == D("7000")
        assert balances.available(Exchange.BYBIT, "USDT") == D("3000")

    def test_transfer_fails_atomically_when_source_insufficient(self):
        balances = _balances("100", "0")
        ok = record_manual_transfer(balances, "USDT", Exchange.BINANCE, Exchange.BYBIT, D("3000"))
        assert not ok
        assert balances.available(Exchange.BINANCE, "USDT") == D("100")
        assert balances.available(Exchange.BYBIT, "USDT") == D("0")
