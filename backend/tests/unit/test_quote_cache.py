from app.exchanges.base import ConnectionStatus
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import QuoteCache


def make_quote(exchange=Exchange.BINANCE, symbol="BTC-USDT", sequence=1, bid="100"):
    return NormalizedQuote(
        exchange=exchange,
        market_type=MarketType.SPOT,
        symbol=symbol,
        bid_price=bid,
        bid_quantity="1",
        ask_price="101",
        ask_quantity="1",
        exchange_timestamp=1_000,
        received_timestamp=1_000,
        sequence=sequence,
    )


def test_update_and_get():
    cache = QuoteCache()
    q = make_quote()
    assert cache.update(q)
    assert cache.get(Exchange.BINANCE, MarketType.SPOT, "BTC-USDT") == q


def test_out_of_order_sequence_dropped():
    cache = QuoteCache()
    cache.update(make_quote(sequence=10, bid="100"))
    assert not cache.update(make_quote(sequence=9, bid="99"))
    kept = cache.get(Exchange.BINANCE, MarketType.SPOT, "BTC-USDT")
    assert kept is not None and kept.sequence == 10


def test_equal_sequence_accepted():
    cache = QuoteCache()
    cache.update(make_quote(sequence=10))
    assert cache.update(make_quote(sequence=10, bid="99"))


def test_snapshot_collects_all_exchanges():
    cache = QuoteCache()
    cache.update(make_quote(exchange=Exchange.BINANCE))
    cache.update(make_quote(exchange=Exchange.BYBIT))
    snap = cache.snapshot(MarketType.SPOT, "BTC-USDT")
    assert set(snap) == {Exchange.BINANCE, Exchange.BYBIT}


def test_snapshot_isolated_by_symbol():
    cache = QuoteCache()
    cache.update(make_quote(symbol="BTC-USDT"))
    cache.update(make_quote(exchange=Exchange.BYBIT, symbol="ETH-USDT"))
    assert set(cache.snapshot(MarketType.SPOT, "BTC-USDT")) == {Exchange.BINANCE}


def test_status_tracking():
    cache = QuoteCache()
    assert cache.get_status(Exchange.OKX) is ConnectionStatus.DISCONNECTED
    cache.set_status(Exchange.OKX, ConnectionStatus.CONNECTED)
    assert cache.get_status(Exchange.OKX) is ConnectionStatus.CONNECTED


def test_quote_count():
    cache = QuoteCache()
    cache.update(make_quote())
    cache.update(make_quote(exchange=Exchange.BYBIT))
    cache.update(make_quote(symbol="ETH-USDT", exchange=Exchange.BINANCE))
    assert cache.quote_count() == 3
