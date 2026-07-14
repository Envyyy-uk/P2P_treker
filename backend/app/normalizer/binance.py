"""Нормалізація Binance spot bookTicker → NormalizedQuote.

Формат (individual stream):
{"u":400900217,"s":"BTCUSDT","b":"63780.10","B":"0.82","a":"63781.20","A":"1.14"}

Spot bookTicker не містить event time, тому exchange_timestamp =
received_timestamp (окремо задокументоване обмеження Binance).
"""

from typing import Any

from app.core.symbols import to_canonical
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote


def normalize_book_ticker(message: dict[str, Any], received_ts_ms: int) -> NormalizedQuote | None:
    # Combined stream загортає payload у {"stream": ..., "data": {...}}
    data = message.get("data", message)
    if "s" not in data or "b" not in data or "a" not in data:
        return None  # службове повідомлення (result підписки тощо)
    if data["b"] in ("", "0") or data["a"] in ("", "0"):
        return None  # порожня сторона стакана — котирування неповне
    try:
        symbol = to_canonical(data["s"], Exchange.BINANCE)
    except KeyError:
        return None  # символ поза нашим mapping
    return NormalizedQuote(
        exchange=Exchange.BINANCE,
        market_type=MarketType.SPOT,
        symbol=symbol,
        bid_price=data["b"],
        bid_quantity=data["B"],
        ask_price=data["a"],
        ask_quantity=data["A"],
        exchange_timestamp=received_ts_ms,
        received_timestamp=received_ts_ms,
        sequence=data.get("u"),
    )
