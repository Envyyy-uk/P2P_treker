"""Нормалізація OKX bbo-tbt → NormalizedQuote.

Формат:
{"arg":{"channel":"bbo-tbt","instId":"BTC-USDT"},
 "data":[{"asks":[["63781.2","1.14","0","2"]],"bids":[["63780.1","0.82","0","2"]],
          "ts":"1670324386802","seqId":123456}]}

Кожне повідомлення містить повні best bid/ask — стан не потрібен.
"""

from typing import Any

from app.core.symbols import to_canonical
from app.models.enums import Exchange, MarketType
from app.models.quote import NormalizedQuote


def normalize_bbo(message: dict[str, Any], received_ts_ms: int) -> NormalizedQuote | None:
    arg = message.get("arg", {})
    if arg.get("channel") != "bbo-tbt" or not message.get("data"):
        return None  # event: subscribe / error / pong
    try:
        symbol = to_canonical(arg.get("instId", ""), Exchange.OKX)
    except KeyError:
        return None
    entry = message["data"][0]
    bids = entry.get("bids") or []
    asks = entry.get("asks") or []
    if not bids or not asks:
        return None  # одна зі сторін порожня
    bid, ask = bids[0], asks[0]
    return NormalizedQuote(
        exchange=Exchange.OKX,
        market_type=MarketType.SPOT,
        symbol=symbol,
        bid_price=bid[0],
        bid_quantity=bid[1],
        ask_price=ask[0],
        ask_quantity=ask[1],
        exchange_timestamp=int(entry["ts"]),
        received_timestamp=received_ts_ms,
        sequence=entry.get("seqId"),
    )
