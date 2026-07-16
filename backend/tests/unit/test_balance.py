"""BalanceManager: available/locked/reserve/release/settle/credit (Фаза 4, п.4)."""

from decimal import Decimal

from app.models.enums import Exchange
from app.paper_trading.balance import BalanceManager

D = Decimal


def test_unset_balance_defaults_to_zero():
    manager = BalanceManager()
    assert manager.available(Exchange.BINANCE, "USDT") == 0


def test_set_and_read_balance():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D("1000"))
    assert manager.available(Exchange.BINANCE, "USDT") == D("1000")


def test_reserve_reduces_available():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D("1000"))
    ok = manager.reserve(Exchange.BINANCE, "USDT", D("300"))
    assert ok
    assert manager.available(Exchange.BINANCE, "USDT") == D("700")


def test_reserve_fails_when_insufficient():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D("100"))
    ok = manager.reserve(Exchange.BINANCE, "USDT", D("300"))
    assert not ok
    assert manager.available(Exchange.BINANCE, "USDT") == D("100")  # unchanged


def test_release_restores_available():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D("1000"))
    manager.reserve(Exchange.BINANCE, "USDT", D("300"))
    manager.release(Exchange.BINANCE, "USDT", D("300"))
    assert manager.available(Exchange.BINANCE, "USDT") == D("1000")


def test_release_never_goes_negative():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D("1000"))
    manager.release(Exchange.BINANCE, "USDT", D("50"))  # more than reserved
    assert manager.get(Exchange.BINANCE, "USDT").locked == 0


def test_settle_deducts_actual_and_releases_remaining_reserve():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D("1000"))
    manager.reserve(Exchange.BINANCE, "USDT", D("300"))  # e.g. reserved for full order
    manager.settle(Exchange.BINANCE, "USDT", D("300"), D("250"))  # only partially filled
    balance = manager.get(Exchange.BINANCE, "USDT")
    assert balance.total == D("750")  # 1000 - 250 actually spent
    assert balance.locked == 0
    assert balance.available == D("750")


def test_credit_increases_total():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "BTC", D("0"))
    manager.credit(Exchange.BINANCE, "BTC", D("0.5"))
    assert manager.available(Exchange.BINANCE, "BTC") == D("0.5")


def test_balances_isolated_per_exchange_and_asset():
    manager = BalanceManager()
    manager.set_balance(Exchange.BINANCE, "USDT", D("100"))
    manager.set_balance(Exchange.BYBIT, "USDT", D("200"))
    manager.set_balance(Exchange.BINANCE, "BTC", D("1"))
    assert manager.available(Exchange.BINANCE, "USDT") == D("100")
    assert manager.available(Exchange.BYBIT, "USDT") == D("200")
    assert manager.available(Exchange.BINANCE, "BTC") == D("1")
