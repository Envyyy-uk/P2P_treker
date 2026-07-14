"""Нормалізація сирих повідомлень бірж у NormalizedQuote."""

from decimal import Decimal

from app.models.enums import Exchange
from app.normalizer.binance import normalize_book_ticker
from app.normalizer.bybit import BybitBookNormalizer
from app.normalizer.okx import normalize_bbo

RECEIVED = 1_784_041_200_141


class TestBinance:
    MSG = {
        "u": 400900217,
        "s": "BTCUSDT",
        "b": "63780.10",
        "B": "0.82",
        "a": "63781.20",
        "A": "1.14",
    }

    def test_normalizes(self):
        q = normalize_book_ticker(self.MSG, RECEIVED)
        assert q is not None
        assert q.exchange is Exchange.BINANCE
        assert q.symbol == "BTC-USDT"
        assert q.bid_price == Decimal("63780.10")
        assert q.ask_quantity == Decimal("1.14")
        assert q.sequence == 400900217
        # spot bookTicker не має event time -> received time
        assert q.exchange_timestamp == RECEIVED

    def test_combined_stream_wrapper(self):
        q = normalize_book_ticker({"stream": "btcusdt@bookTicker", "data": self.MSG}, RECEIVED)
        assert q is not None and q.symbol == "BTC-USDT"

    def test_service_message_ignored(self):
        assert normalize_book_ticker({"result": None, "id": 1}, RECEIVED) is None

    def test_unknown_symbol_ignored(self):
        assert normalize_book_ticker({**self.MSG, "s": "DOGEUSDT"}, RECEIVED) is None

    def test_empty_side_ignored(self):
        assert normalize_book_ticker({**self.MSG, "b": "0"}, RECEIVED) is None


class TestBybit:
    SNAPSHOT = {
        "topic": "orderbook.1.BTCUSDT",
        "ts": 1672304484978,
        "type": "snapshot",
        "data": {
            "s": "BTCUSDT",
            "b": [["16493.50", "0.006"]],
            "a": [["16611.00", "0.029"]],
            "u": 18521288,
            "seq": 7961638724,
        },
    }

    def test_snapshot(self):
        n = BybitBookNormalizer()
        q = n.handle(self.SNAPSHOT, RECEIVED)
        assert q is not None
        assert q.symbol == "BTC-USDT"
        assert q.bid_price == Decimal("16493.50")
        assert q.exchange_timestamp == 1672304484978
        assert q.sequence == 18521288

    def test_delta_updates_one_side_keeps_other(self):
        n = BybitBookNormalizer()
        n.handle(self.SNAPSHOT, RECEIVED)
        delta = {
            "topic": "orderbook.1.BTCUSDT",
            "ts": 1672304485000,
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [["16494.00", "0.01"]], "a": [], "u": 18521289},
        }
        q = n.handle(delta, RECEIVED + 20)
        assert q is not None
        assert q.bid_price == Decimal("16494.00")
        assert q.ask_price == Decimal("16611.00")  # без змін

    def test_zero_quantity_removes_side(self):
        n = BybitBookNormalizer()
        n.handle(self.SNAPSHOT, RECEIVED)
        delta = {
            "topic": "orderbook.1.BTCUSDT",
            "ts": 1672304485000,
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [["16493.50", "0"]], "a": [], "u": 18521290},
        }
        assert n.handle(delta, RECEIVED + 20) is None  # bid зник -> неповне

    def test_delta_before_snapshot_ignored(self):
        n = BybitBookNormalizer()
        delta = {
            "topic": "orderbook.1.BTCUSDT",
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [["1", "1"]], "a": [], "u": 5},
        }
        assert n.handle(delta, RECEIVED) is None

    def test_reset_after_reconnect_waits_for_snapshot(self):
        n = BybitBookNormalizer()
        n.handle(self.SNAPSHOT, RECEIVED)
        n.reset()
        delta = {
            "topic": "orderbook.1.BTCUSDT",
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [["1", "1"]], "a": [["2", "1"]], "u": 99},
        }
        assert n.handle(delta, RECEIVED) is None

    def test_service_message_ignored(self):
        assert BybitBookNormalizer().handle({"op": "pong"}, RECEIVED) is None


class TestOKX:
    MSG = {
        "arg": {"channel": "bbo-tbt", "instId": "BTC-USDT"},
        "data": [
            {
                "asks": [["63781.2", "1.14", "0", "2"]],
                "bids": [["63780.1", "0.82", "0", "2"]],
                "ts": "1670324386802",
                "seqId": 123456,
            }
        ],
    }

    def test_normalizes(self):
        q = normalize_bbo(self.MSG, RECEIVED)
        assert q is not None
        assert q.exchange is Exchange.OKX
        assert q.symbol == "BTC-USDT"
        assert q.ask_price == Decimal("63781.2")
        assert q.exchange_timestamp == 1670324386802
        assert q.sequence == 123456

    def test_subscribe_ack_ignored(self):
        ack = {"event": "subscribe", "arg": {"channel": "bbo-tbt", "instId": "BTC-USDT"}}
        assert normalize_bbo(ack, RECEIVED) is None

    def test_missing_bid_side_ignored(self):
        msg = {
            "arg": {"channel": "bbo-tbt", "instId": "BTC-USDT"},
            "data": [{"asks": [["1", "1", "0", "1"]], "bids": [], "ts": "1", "seqId": 1}],
        }
        assert normalize_bbo(msg, RECEIVED) is None
