"""HistoryRecorder: семплінг quotes_1s і трекінг spread events у DbWriter."""

from decimal import Decimal

from app.core.config import DatabaseConfig, ExchangeConfig, Settings, TradingConfig
from app.database.models import Quote1s, SpreadEvent
from app.database.writer import DbWriter
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote
from app.quote_cache.cache import QuoteCache, now_ms
from app.services.history_recorder import HistoryRecorder
from app.spread.engine import SpreadEngine

D = Decimal


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        trading=TradingConfig(
            symbols=["BTC-USDT"],
            spread_threshold=D("0.001"),
            min_executable_notional=D("0"),
        ),
        database=DatabaseConfig(batch_max_rows=500, batch_max_interval_ms=10_000),
        exchanges={
            Exchange.BINANCE: ExchangeConfig(taker_fee=D("0.001")),
            Exchange.BYBIT: ExchangeConfig(taker_fee=D("0.001")),
            Exchange.OKX: ExchangeConfig(taker_fee=D("0.001")),
        },
    )


def make_quote(exchange, bid="100", ask="100.1"):
    ts = now_ms()
    return NormalizedQuote(
        exchange=exchange,
        market_type=MarketType.SPOT,
        symbol="BTC-USDT",
        bid_price=bid,
        bid_quantity="1",
        ask_price=ask,
        ask_quantity="1",
        exchange_timestamp=ts,
        received_timestamp=ts,
        sequence=1,
    )


async def null_flush(grouped):
    pass


def drain_tables(writer: DbWriter) -> set[str]:
    """Тестовий хелпер: витягує назви таблиць із черги, не запускаючи consumer."""
    tables: set[str] = set()
    while True:
        try:
            table, _row = writer._queue.get_nowait()
        except Exception:  # asyncio.QueueEmpty
            break
        tables.add(table)
    return tables


def test_sample_quotes_once_enqueues_one_row_per_live_quote():
    settings = make_settings()
    cache = QuoteCache()
    cache.update(make_quote(Exchange.BINANCE))
    cache.update(make_quote(Exchange.BYBIT))
    writer = DbWriter(flush=null_flush, config=settings.database)
    engine = SpreadEngine(cache, settings)
    recorder = HistoryRecorder(cache, engine, writer, settings)

    count = recorder.sample_quotes_once()

    assert count == 2
    assert writer.metrics.enqueued_total == 2
    assert drain_tables(writer) == {Quote1s.__tablename__}


def test_sample_quotes_once_skips_missing_exchange():
    settings = make_settings()
    cache = QuoteCache()
    cache.update(make_quote(Exchange.BINANCE))
    writer = DbWriter(flush=null_flush, config=settings.database)
    engine = SpreadEngine(cache, settings)
    recorder = HistoryRecorder(cache, engine, writer, settings)

    assert recorder.sample_quotes_once() == 1


def test_process_events_once_enqueues_closed_events():
    settings = make_settings()
    cache = QuoteCache()
    cache.update(make_quote(Exchange.BINANCE, bid="100", ask="100"))
    cache.update(make_quote(Exchange.BYBIT, bid="105", ask="105.1"))  # great spread
    writer = DbWriter(flush=null_flush, config=settings.database)
    engine = SpreadEngine(cache, settings)
    recorder = HistoryRecorder(cache, engine, writer, settings)

    recorder.process_events_once()  # opens events, nothing closed yet
    assert writer.metrics.enqueued_total == 0

    # Spread collapses -> events should close on next tick
    cache.update(make_quote(Exchange.BYBIT, bid="100", ask="100.01"))
    recorder.process_events_once()
    assert writer.metrics.enqueued_total > 0
    assert SpreadEvent.__tablename__ in drain_tables(writer)


async def test_stop_flushes_open_events():
    settings = make_settings()
    cache = QuoteCache()
    cache.update(make_quote(Exchange.BINANCE, bid="100", ask="100"))
    cache.update(make_quote(Exchange.BYBIT, bid="105", ask="105.1"))
    writer = DbWriter(flush=null_flush, config=settings.database)
    engine = SpreadEngine(cache, settings)
    recorder = HistoryRecorder(cache, engine, writer, settings)

    recorder.process_events_once()  # opens an event, still open
    await recorder.start()
    await recorder.stop()  # graceful shutdown must close pending events

    assert writer.metrics.enqueued_total >= 1
