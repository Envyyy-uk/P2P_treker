# Формули розрахунку (Фаза 0, п.12)

Реалізація: `backend/app/spread/formulas.py`. Усі розрахунки — **тільки `Decimal`**,
float заборонений. Кожна зміна формул інкрементує `CALCULATION_VERSION` і
застосовується **тільки проспективно** (уже збережені `spread_events` не
перераховуються — див. Фазу 2 плану).

## Позначення

- `buy_ask` — ask-ціна на біржі купівлі (ми купуємо по ask);
- `sell_bid` — bid-ціна на біржі продажу (ми продаємо по bid);
- `buy_fee`, `sell_fee` — taker-комісії відповідних бірж (частки, напр. `0.001`);
- `buy_ask_qty`, `sell_bid_qty` — обсяги top-of-book.

## Gross Spread

```text
gross_spread = sell_bid / buy_ask - 1
```

## Net Spread (мультиплікативна модель)

```text
net_return = sell_bid × (1 - sell_fee) / (buy_ask × (1 + buy_fee)) - 1
```

Для реалістичної оцінки завжди використовуємо **taker** fees.
Формула може уточнюватися для бірж, які стягують комісію інакше
(наприклад, у base-активі) — це фіксується новою `calculation_version`.

## Доступний обсяг (top-of-book MVP)

```text
executable_quantity = min(buy_ask_qty, sell_bid_qty)
executable_notional = executable_quantity × buy_ask
```

## Очікуваний прибуток

```text
expected_gross_profit = executable_quantity × (sell_bid - buy_ask)
expected_net_profit   = executable_quantity × buy_ask × net_return
```

## Правила валідності

Можливість НЕ вважається валідною, якщо:

- будь-яке котирування stale: `current_time - received_timestamp > MAX_QUOTE_AGE_MS`;
- `abs(exchange_a_timestamp - exchange_b_timestamp) > MAX_TIMESTAMP_DIFF_MS`;
- `executable_quantity < MIN_EXECUTABLE_QUANTITY`;
- `executable_notional < MIN_EXECUTABLE_NOTIONAL`;
- котирування належать різним market types (Spot ≠ Futures).

## Напрямки

Для кожної пари бірж рахуємо **обидва** напрямки. Для 3 бірж — 6 напрямків:
Binance→Bybit, Bybit→Binance, Binance→OKX, OKX→Binance, Bybit→OKX, OKX→Bybit.
