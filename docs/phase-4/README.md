# Фаза 4 — Paper Trading і симуляція: що зроблено

Повністю in-memory симуляція виконання арбітражної угоди (два ордери на
двох біржах) поверх реального Order Book стану, VWAP-заповнення,
торгових обмежень і балансу — без жодного реального виклику біржі.
Не залежить від PostgreSQL (`DATABASE__ENABLED=false` не блокує роботу).

| Компонент плану | Реалізація |
|-----------------|------------|
| Order Book (snapshot/delta, sequence) | `app/orderbook/book.py`: `OrderBook` — генерична, exchange-agnostic модель з одним монотонним `sequence`; `apply_snapshot`/`apply_delta` (delta повертає `False` і десинхронізує при пропуску sequence, ігнорує застарілі/дублікати) |
| VWAP | `app/orderbook/vwap.py`: `compute_vwap(levels, target_quantity)` — обхід рівнів до заповнення цільового обсягу |
| Slippage | `app/orderbook/vwap.py`: `buy_slippage_pct`/`sell_slippage_pct` — відхилення VWAP від top-of-book |
| Торгові обмеження (min qty/notional, tick/step, precision) | `app/paper_trading/rules.py`: `SymbolRules`, `validate_order` (накопичує всі порушення), `round_to_tick`/`round_to_step` |
| Available/locked balance | `app/paper_trading/balance.py`: `BalanceManager` — `reserve`/`release`/`settle`/`credit`, ізольовано по `(exchange, asset)` |
| Rate limits | `app/paper_trading/engine.py`: `RateLimiter` — фіксоване 1-секундне вікно (спрощена модель, не претендує на точне відтворення алгоритму конкретної біржі) |
| Paper Trading Engine (partial fills, затримка між ордерами, slippage, rejection, timeout, cancellation, різні ціни виконання, комісії, PnL) | `app/paper_trading/engine.py`: `PaperTradingEngine.execute_arbitrage` — buy leg → (за потреби) inter-order delay → sell leg, розмір sell leg обмежено фактичним filled_quantity buy leg; `_settle` рахує `realized_pnl` через `app.spread.formulas.net_spread` (Фаза 1, без дублювання формул) |
| Testnet/Sandbox клієнт (create/status/partial fill/cancel/retry/idempotency/reconnect) | `app/testnet/binance.py`: `BinanceTestnetClient` — HMAC-SHA256 підпис, exponential backoff тільки для 5xx/мережевих помилок, ідемпотентність через локальний `client_order_id` кеш |

## API

```text
POST /api/paper-trading/execute
{
  "symbol": "BTC-USDT",
  "buy_exchange": "binance",
  "sell_exchange": "bybit",
  "quantity": "1",
  "buy_book": {"bids": [...], "asks": [{"price": "100", "quantity": "10"}]},
  "sell_book": {"bids": [{"price": "102", "quantity": "10"}], "asks": [...]},
  "quote_asset": "USDT",           // опціонально, дефолт USDT
  "simulated_ack_latency_ms": 0    // опціонально, для тестування timeout
}

GET  /api/paper-trading/balances
POST /api/paper-trading/balances {"exchange": "binance", "asset": "USDT", "total": "5000"}
```

Order book передається в тілі запиту, а не тягнеться з live WS —
див. "Свідомо не зроблено" нижче.

## Як працює execute_arbitrage

1. **Buy leg**: перевірка timeout (симульована ack-затримка) → перевірка
   наявності top-of-book → `validate_order` (min qty/notional, tick/step) →
   rate limiter → резервування балансу (`quantity*price` у quote-активі)
   → `compute_vwap` по `asks_sorted()` → FILLED/PARTIALLY_FILLED, комісія
   від notional.
2. Якщо buy leg нічого не заповнив (rejected/expired) — sell leg одразу
   CANCELED, `realized_pnl=None`, **без** очікування inter-order delay.
3. Інакше — очікування `inter_order_delay_ms` (реальна модельована
   затримка між двома ногами арбітражу), потім **sell leg розміром
   `buy_order.filled_quantity`** (частковий buy природно обмежує sell).
4. `_settle`: `matched_quantity = min(buy.filled, sell.filled)`,
   `leftover_base_quantity = buy.filled - matched` (непродана частина —
   неявний ризик, явно НЕ оцінюється в грошах); `realized_pnl` тільки
   якщо є хоч якийсь matched обсяг і обидві ноги мають avg_fill_price;
   `net_spread_after_slippage_pct` — той самий `formulas.net_spread`,
   що й live Spread Engine, застосований до фактичних (post-slippage)
   цін виконання, а не top-of-book.

## Свідомо не зроблено в цьому проході

- **Live WS depth-адаптери для Binance/Bybit/OKX** (реальний parsing
  snapshot+delta протоколу кожної біржі в `OrderBook`) — не реалізовано.
  Причини: (а) неможливо живо перевірити в цьому середовищі — WSS
  заблоковано ще з Фази 1; (б) генерична `OrderBook`-модель — цінна й
  тестована сама по собі; (в) бюджет зусиль пріоритезовано на
  VWAP/slippage/rules/balance/engine — власне "симуляцію", заради якої
  ця фаза існує. Наслідок: `/api/paper-trading/execute` приймає рівні
  book у тілі запиту, а не читає їх із live cache. Коли з'явиться
  реальна WS-глибина, підключення — окремий, ізольований крок (adapter
  → normalizer → та сама `OrderBook.apply_snapshot/apply_delta`).
- **Реальний мережевий виклик до Binance Testnet** — спроба зроблена
  (див. нижче), але недоступна в цьому sandbox (той самий клас обмежень,
  що й live WS-фіди з Фази 0/1).

## Перевірено в цьому середовищі

- Юніт-тести (без I/O): `test_orderbook.py` (13, включно з sequence
  gap/resync), `test_vwap.py` (VWAP + slippage), `test_trading_rules.py`
  (rounding + валідація, накопичення кількох порушень одночасно),
  `test_balance.py` (reserve/release/settle/credit, ізоляція по
  exchange+asset), `test_paper_trading_engine.py` (успішна угода з
  позитивним PnL що збігається з ручним розрахунком; VWAP на
  багаторівневому стакані дає ціну, відмінну від top-of-book; partial
  fill на buy обмежує sell; partial fill на sell лишає
  `leftover_base_quantity`; rejection — no liquidity/rule
  violation/insufficient balance/rate limit; timeout при завеликій
  ack-затримці; inter-order delay реально awaited (`asyncio.sleep`
  замокано і перевірено `assert_awaited_once_with`), і НЕ awaited, коли
  buy leg відхилено; cancel_order звільняє резерв і є no-op для
  термінальних станів).
- Інтеграційні тести (реальний `app`, `TestClient`, БД вимкнена):
  `test_paper_trading_routes.py` — успішна угода через HTTP, 400 на
  однакову біржу/невалідну кількість, rejected buy leg з порожнім
  стаканом коректно каскадується в canceled sell, `/balances`
  показує дефолтне щедре фінансування, `POST /balances` змінює баланс
  і відображається в наступному `GET`, брак коштів після зменшення
  балансу коректно відхиляє ордер з поясненням причини.
- `BinanceTestnetClient` (`test_testnet_binance.py`, 11 тестів, увесь
  через `httpx.MockTransport`, жодних реальних мережевих викликів):
  успішне створення ордера (перевірено підпис і заголовок API-ключа),
  ідемпотентний повтор того самого `client_order_id` НЕ робить другий
  HTTP-виклик, partial fill статус, нульове заповнення → `avg_price is
  None`, 5xx ретраїться і зрештою встигає, 5xx після вичерпання спроб
  кидає `TestnetRetryableError`, мережева помилка (`httpx.ConnectError`)
  ретраїться так само, 4xx кидає `TestnetRejectedError` **одразу, без
  жодної повторної спроби**, отримання статусу/скасування ордера,
  валідація "потрібен client_order_id або exchange_order_id".
- Реальна спроба мережевого виклику: `GET
  https://testnet.binance.vision/api/v3/ping` через `httpx` — proxy
  повернув `403` (`gateway answered 403 to CONNECT`), підтверджено через
  `$HTTPS_PROXY/__agentproxy/status` (`recentRelayFailures`: host
  `testnet.binance.vision:443` не в allowlist). Той самий клас
  обмежень, що документувався для live WS у Фазах 0/1 — не проблема
  коду клієнта, а мережева політика цього sandbox.
- Повний прогін: 268 тестів (усього по backend, +11 від Фази 4), `ruff
  check` — чисто, `black --check` — чисто, `mypy app` (strict) —
  `Success: no issues found in 71 source files`.

## Обмеження / межі відповідальності

- `RateLimiter` — фіксоване вікно, спрощена модель; не відтворює точний
  алгоритм жодної конкретної біржі (token bucket, weight-based ліміти
  Binance тощо) — для цього потрібна окрема реалізація, коли з'явиться
  реальна інтеграція з біржею (Фаза 5).
- `BinanceTestnetClient` — REST-only. "Reconnect" у сенсі плану
  застосовується лише до транзієнтних мережевих помилок одного запиту
  (уже покрито retry policy); user-data WS стрім для ордерів (якщо
  знадобиться в Фазі 5) вимагатиме окремої reconnect-логіки за патерном
  live quote WS-адаптерів Фази 1.
- `leftover_base_quantity` (куплено, але не продано через частковий sell
  fill) навмисно НЕ оцінюється в PnL — це відкрита позиція/ризик, а не
  завершена арбітражна угода; оцінка такої позиції — за межами Paper
  Trading Engine (можливо, Risk Manager, Фаза 5.1).
