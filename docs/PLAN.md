# Повний план побудови Crypto Arbitrage Platform

## Мета проєкту

Побудувати модульну платформу для моніторингу міжбіржових спредів, збереження історії, аналітики, paper trading і подальшого безпечного переходу до напівавтоматичного або автоматичного виконання угод.

На першому етапі система повинна працювати як **Spread Monitor**, а не як повноцінний торговий бот.

---

## Зміни у версії 3 (виправлені недоліки)

- Додано перевірку Terms of Service бірж щодо автоматизованої торгівлі (Фаза 0, п.13).
- Додано політику ротації API-ключів та секретів (Фаза 0.1, п.7).
- Додано окрему Фазу 2.2 — Backup і Disaster Recovery для БД (раніше була відсутня).
- Додано Фазу 3.1 — Historical Backtesting Engine на історичних даних (раніше аналітика описувала тільки статистику по вже зібраних live-даних, без окремого backtesting-двигуна для перевірки стратегії "заднім числом").
- Уточнено правило versioning: зміна формули spread engine ніколи не перераховує заднім числом уже збережені `spread_events` — нова `calculation_version` застосовується тільки проспективно (Фаза 2, `spread_events`).
- Додано graceful shutdown (SIGTERM) для адаптерів бірж — коректне закриття WS і флаш черги перед зупинкою (Фаза 1, п.2).
- Уточнено Alembic як інструмент міграцій БД (структура проєкту вже мала папку `migrations/`, але без інструменту).
- Додано резервні NTP-сервери замість одного (Фаза 0, п.10).
- Додано механізм періодичного оновлення комісій з API біржі замість статичного конфіга (Фаза 0, п.5).
- Уточнено мінімальний поріг покриття тестами для критичних модулів (Фаза 8).

---

# ФАЗА 0 — ПІДГОТОВКА

1. Обрати тип ринку для MVP — тільки Spot.
2. Обрати 5–10 торгових пар, наприклад:
   - BTC/USDT;
   - ETH/USDT;
   - SOL/USDT;
   - BNB/USDT;
   - XRP/USDT.
3. Створити таблицю відповідності символів між біржами:
   - Binance: BTCUSDT;
   - Bybit: BTCUSDT;
   - OKX: BTC-USDT.
4. Не змішувати різні типи ринку:
   - Spot;
   - Perpetual Futures;
   - Delivery Futures;
   - Inverse Futures.
5. Зберегти торгові комісії кожної біржі:
   - Maker Fee;
   - Taker Fee.
   - Комісії можуть змінюватись залежно від VIP-рівня/обсягу торгів — не хардкодити назавжди. Додати періодичне (наприклад раз на добу) оновлення через account/fee endpoint кожної біржі, а не тільки статичний конфіг.
6. Визначити максимальний допустимий вік котирування, наприклад 1 секунда.
7. Визначити максимальну допустиму різницю часу між котируваннями різних бірж.
8. Підготувати єдину модель даних для всіх бірж.
9. Перевірити доступність потрібних API та WebSocket-каналів для акаунтів і регіонів, які будуть використовуватися.
10. Налаштувати NTP-синхронізацію часу на сервері через chrony або ntpd, з кількома резервними NTP-серверами (один сервер — точка відмови для всієї freshness-перевірки).
11. При старті застосунку перевіряти дрейф системного часу.
12. Визначити формули розрахунку:
    - Gross Spread;
    - Net Spread;
    - доступного обсягу;
    - очікуваного прибутку.
13. Перевірити Terms of Service кожної біржі щодо автоматизованої торгівлі та ботів — порушення умов може призвести до блокування акаунту незалежно від того, наскільки коректний код.

---

# ФАЗА 0.1 — БЕЗПЕКА

Безпека закладається одразу, навіть для read-only MVP.

1. API-ключі бірж:
   - спочатку тільки права read;
   - пізніше можна додати trade;
   - ніколи не використовувати withdraw;
   - увімкнути IP whitelist;
   - створювати окремі ключі для dev, staging і production.
2. Не зберігати API-ключі:
   - у коді;
   - у Git;
   - у відкритому вигляді в БД;
   - у логах.
3. Використовувати:
   - `.env` для локальної розробки;
   - secrets manager для production.
4. Розділити конфігурацію за середовищами:
   - dev;
   - staging;
   - production.
5. Додати маскування секретів у логах.
6. Перевірити, щоб повідомлення про помилки не містили:
   - токени;
   - API-ключі;
   - повні заголовки авторизації;
   - приватні параметри запитів.
7. Ввести політику ротації ключів:
   - плановий термін дії кожного ключа (наприклад 90 днів);
   - процедура заміни без даунтайму (новий ключ додається, старий деактивується після підтвердження);
   - моніторинг дати останньої ротації і алерт, якщо термін наближається.

---

# ФАЗА 0.2 — CONFIGURATION

1. Використовувати Pydantic Settings.
2. Додати `.env.example` без реальних секретів.
3. Додати валідацію конфігурації при старті застосунку.
4. Розділити конфігурацію на секції:
   - Exchange Config;
   - Trading Config;
   - Database Config;
   - WebSocket Config;
   - Logging Config;
   - Security Config;
   - Monitoring Config.
5. Винести в конфігурацію:
   - список бірж;
   - список пар;
   - комісії;
   - stale threshold;
   - максимальний timestamp difference;
   - частоту push на фронтенд;
   - розмір async Queue;
   - політику переповнення Queue;
   - пороги спреду;
   - мінімальний доступний обсяг.
6. Зміни конфігурації не повинні вимагати редагування бізнес-логіки.

---

# ФАЗА 0.3 — СТРУКТУРА ПРОЄКТУ

Рекомендована структура backend:

```text
backend/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   └── websocket/
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── security.py
│   │   └── exceptions.py
│   ├── exchanges/
│   │   ├── base.py
│   │   ├── binance/
│   │   ├── bybit/
│   │   └── okx/
│   ├── normalizer/
│   ├── quote_cache/
│   ├── spread/
│   ├── analytics/
│   ├── execution/
│   ├── risk/
│   ├── paper_trading/
│   ├── notifications/
│   ├── monitoring/
│   ├── database/
│   ├── models/
│   ├── repositories/
│   ├── services/
│   └── main.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── migrations/        # Alembic — жодних ручних ALTER TABLE в production
├── Dockerfile
├── pyproject.toml
├── .env.example
└── README.md
```

Рекомендована структура frontend:

```text
frontend/
├── src/
│   ├── api/
│   ├── components/
│   ├── features/
│   ├── hooks/
│   ├── pages/
│   ├── store/
│   ├── types/
│   ├── utils/
│   └── main.tsx
├── public/
├── Dockerfile
└── package.json
```

---

# ФАЗА 1 — LIVE МОНІТОРИНГ

## 1. Exchange Adapters

Створити окремий WebSocket Adapter для кожної біржі:

- BinanceAdapter;
- BybitAdapter;
- OKXAdapter.

Кожен адаптер повинен реалізовувати єдиний інтерфейс:

```text
connect()
disconnect()
subscribe(symbols)
unsubscribe(symbols)
handle_message(message)
health_status()
```

## 2. Надійність WebSocket-з'єднань

Для кожної біржі реалізувати:

- автоматичне перепідключення;
- exponential backoff;
- heartbeat;
- ping/pong;
- повторну підписку після reconnect;
- контроль часу останнього повідомлення;
- timeout detection;
- логування disconnect/reconnect;
- перевірку sequence ID;
- обробку snapshot і delta;
- скидання локального стакана після нового snapshot;
- REST snapshot як резервний механізм, якщо це потрібно конкретній біржі;
- graceful shutdown на SIGTERM/SIGINT: коректно закрити всі WS-з'єднання, дочекатись флашу async Queue в БД (з таймаутом), і тільки тоді завершити процес — інакше рестарт/деплой втрачає останні дані з черги.

## 3. Нормалізація даних

Усі біржі повинні повертати єдину модель котирування:

```json
{
  "exchange": "binance",
  "market_type": "spot",
  "symbol": "BTC-USDT",
  "bid_price": "63780.10",
  "bid_quantity": "0.82",
  "ask_price": "63781.20",
  "ask_quantity": "1.14",
  "exchange_timestamp": 1784041200123,
  "received_timestamp": 1784041200141,
  "sequence": 123456
}
```

## 4. Quote Cache

Зберігати в пам'яті:

- Bid Price;
- Ask Price;
- Bid Quantity;
- Ask Quantity;
- Exchange Timestamp;
- Received Timestamp;
- Sequence ID;
- Market Type;
- Connection Status.

Рекомендована структура:

```text
quotes[exchange][market_type][symbol]
```

Для MVP використовувати один процес FastAPI, тому що кілька worker-процесів мають окрему пам'ять.

Не запускати MVP так:

```bash
uvicorn app.main:app --workers 4
```

Для MVP краще:

```bash
uvicorn app.main:app --workers 1
```

## 5. Перевірка актуальності даних

Для кожного котирування обчислювати:

- quote_age_ms;
- timestamp_difference_ms;
- is_stale.

Не використовувати котирування, якщо:

```text
current_time - received_timestamp > MAX_QUOTE_AGE_MS
```

або:

```text
abs(exchange_a_timestamp - exchange_b_timestamp) > MAX_TIMESTAMP_DIFF_MS
```

Застарілі котирування повинні позначатися в UI окремим статусом.

## 6. Spread Engine

Розраховувати обидва напрямки для кожної пари бірж.

Приклад:

```text
Купити на Binance → Продати на Bybit
Купити на Bybit → Продати на Binance
```

Для трьох бірж потрібно рахувати всі напрямки:

```text
Binance → Bybit
Bybit → Binance
Binance → OKX
OKX → Binance
Bybit → OKX
OKX → Bybit
```

Gross Spread:

```text
gross_spread = sell_bid / buy_ask - 1
```

Net Spread повинен враховувати комісію купівлі та продажу.

Рекомендована мультиплікативна модель:

```text
net_return = sell_bid × (1 - sell_fee) / (buy_ask × (1 + buy_fee)) - 1
```

Формула може змінюватися залежно від того, як конкретна біржа стягує комісію.

Обов'язково використовувати Decimal, а не float.

## 7. Обсяг і ліквідність

Для top-of-book MVP:

```text
executable_quantity = min(buy_ask_quantity, sell_bid_quantity)
```

Також розраховувати:

- executable_notional;
- expected_gross_profit;
- expected_net_profit.

Не показувати можливість як валідну, якщо доступний обсяг менший за мінімальний поріг.

## 8. Юніт-тести Spread Engine

Перевірити щонайменше такі сценарії:

- однакові ціни;
- нульовий обсяг;
- відсутній bid;
- відсутній ask;
- stale data;
- різні market type;
- неправильно визначений напрямок buy/sell;
- spread менший за комісії;
- spread більший за комісії;
- округлення Decimal;
- дуже мала кількість;
- дуже велика ціна;
- timestamp mismatch.

## 9. FastAPI WebSocket

Передавати на frontend вже готові розраховані дані.

Не відправляти кожен біржовий тик.

Рекомендована частота push:

```text
5–10 оновлень за секунду
```

Формат повідомлення:

```json
{
  "type": "spread_update",
  "sequence": 15412,
  "generated_at": 1784041200200,
  "data": [
    {
      "symbol": "BTC-USDT",
      "buy_exchange": "binance",
      "sell_exchange": "bybit",
      "buy_price": "63781.20",
      "sell_price": "63842.70",
      "gross_spread_pct": "0.0964",
      "net_spread_pct": "-0.1037",
      "max_top_quantity": "0.42",
      "quote_age_ms": 120,
      "stale": false
    }
  ]
}
```

Додати connection manager для клієнтів WebSocket.

Передбачити:

- відключення клієнта;
- повільного клієнта;
- обмежену client queue;
- heartbeat між backend і frontend;
- sequence number для виявлення пропущених оновлень.

## 10. React Dashboard

Створити таблицю з колонками:

- Symbol;
- Market Type;
- Buy Exchange;
- Sell Exchange;
- Buy Ask;
- Sell Bid;
- Gross Spread;
- Net Spread;
- Available Quantity;
- Available Notional;
- Expected Profit;
- Quote Age;
- Status.

Додати:

- сортування за Net Spread;
- фільтрацію за біржею;
- фільтрацію за парою;
- фільтрацію за мінімальним спредом;
- фільтрацію за мінімальним обсягом;
- кольорове підсвічування;
- окреме позначення stale data;
- статус Connected / Reconnecting / Offline;
- час останнього оновлення;
- паузу UI без зупинки backend;
- можливість відкрити деталі конкретної пари.

Order Book повинен з'являтися справа тільки після відкриття конкретної монети або торгової пари.

Загальний екран не повинен масштабуватися жестом zoom. Дозволене тільки вертикальне прокручування, якщо це передбачено дизайном.

---

# ФАЗА 2 — ЗБЕРЕЖЕННЯ ІСТОРІЇ

## 1. База даних

Використовувати:

- PostgreSQL для MVP;
- TimescaleDB як опціональне розширення для time-series даних.

## 2. Основні таблиці

### quotes_1s

Поля:

- id;
- timestamp;
- exchange;
- symbol;
- market_type;
- bid_price;
- bid_quantity;
- ask_price;
- ask_quantity;
- exchange_timestamp;
- received_timestamp;
- quote_age_ms.

### spread_events

Поля:

- id;
- start_timestamp;
- end_timestamp;
- symbol;
- market_type;
- buy_exchange;
- sell_exchange;
- start_net_spread;
- max_net_spread;
- average_net_spread;
- executable_quantity;
- executable_notional;
- estimated_profit;
- threshold;
- calculation_version.

Правило versioning: якщо формула spread engine змінюється, `calculation_version` інкрементується і застосовується тільки до нових подій. Уже збережені `spread_events` з попередньою версією НІКОЛИ не перераховуються заднім числом — інакше історична аналітика і backtesting стають недостовірними.

### spread_snapshots

Опціональна таблиця:

- timestamp;
- symbol;
- buy_exchange;
- sell_exchange;
- buy_ask;
- sell_bid;
- gross_spread_bps;
- net_spread_bps;
- max_quantity;
- quote_age_ms;
- timestamp_diff_ms;
- calculation_version.

## 3. Async Queue

Запис у БД виконувати через окрему async Queue.

Використовувати:

```python
asyncio.Queue(maxsize=N)
```

Обов'язково визначити політику переповнення:

- drop-oldest;
- drop-newest;
- block producer;
- аварійний log + metric.

Для live market data краще зазвичай не блокувати основний collector.

## 4. Batch Insert

Не записувати кожен tick окремим SQL-запитом.

Використовувати batch insert:

- за кількістю записів;
- за часовим інтервалом;
- залежно від того, що спрацює першим.

## 5. Стратегія збереження

Не зберігати всі сирі повідомлення для всіх пар без обмежень.

Рекомендовані варіанти:

1. Один snapshot за секунду.
2. Запис тільки при зміні спреду більше заданого порогу.
3. Запис початку, максимуму і завершення spread event.
4. Сирі тики зберігати лише для кількох тестових пар.

---

# ФАЗА 2.1 — RETENTION І РОЗМІР БД

1. Партиціонувати таблиці за датою.
2. Для TimescaleDB використовувати hypertables.
3. Визначити retention policy:
   - сирі дані — N днів;
   - секундні дані — довше;
   - хвилинні агрегати — ще довше;
   - spread events — зберігати постійно або за окремою політикою.
4. Додати downsampling:
   - 1 секунда;
   - 10 секунд;
   - 1 хвилина;
   - 5 хвилин.
5. Автоматично видаляти або архівувати застарілі партиції.
6. Використовувати cron або pg_cron.
7. Додати метрики:
   - DB write latency;
   - queue size;
   - dropped records;
   - batch size;
   - database storage size.

---

# ФАЗА 2.2 — BACKUP І DISASTER RECOVERY

Оригінальний план описував retention (видалення старих даних), але не відновлення після втрати даних — це різні речі.

1. Регулярний `pg_dump` або WAL-архівування (point-in-time recovery) для PostgreSQL.
2. Зберігати бекапи окремо від основного сервера (інший диск/регіон/S3-сумісне сховище).
3. Визначити:
   - RPO (Recovery Point Objective) — скільки даних прийнятно втратити;
   - RTO (Recovery Time Objective) — за який час система має відновитись.
4. Періодично перевіряти, що бекап реально відновлюється (тестове відновлення на окремому середовищі, не тільки перевірка, що файл бекапу існує).
5. `spread_events` і `audit log` мають вищий пріоритет відновлення, ніж сирі `quotes_1s` — це різні за критичністю дані.
6. Задокументувати процедуру відновлення в Incident Response Guide (Фаза 12).

---

# ФАЗА 3 — АНАЛІТИКА

## 1. API Endpoint історії

Параметри:

- symbol;
- buy_exchange;
- sell_exchange;
- market_type;
- from;
- to;
- interval.

## 2. Threshold Events

Точно визначити spread event.

Початок події:

```text
net_spread перетнув поріг знизу вгору
```

Кінець події:

```text
net_spread опустився нижче порогу
```

Тривалість:

```text
end_timestamp - start_timestamp
```

Додати мінімальну тривалість події, наприклад 500 мс, щоб не враховувати випадкові короткі стрибки.

## 3. Статистика

Розраховувати:

- кількість подій;
- загальну тривалість;
- середню тривалість;
- медіанну тривалість;
- максимальну тривалість;
- середній Net Spread;
- максимальний Net Spread;
- середній доступний обсяг;
- середній очікуваний прибуток;
- відсоток подій, що тривали довше мінімального часу.

## 4. Фільтри

Додати:

- мінімальний Net Spread;
- мінімальний доступний обсяг;
- мінімальну тривалість;
- конкретну біржу;
- конкретну пару;
- напрямок арбітражу;
- Spot або Futures;
- часовий діапазон.

## 5. Графіки

Показувати:

- Gross Spread;
- Net Spread;
- Threshold;
- stale periods;
- початок і кінець opportunity;
- доступний обсяг;
- очікуваний прибуток.

Не передавати сотні тисяч точок на frontend.

Backend повинен виконувати:

- агрегацію;
- downsampling;
- pagination;
- обмеження максимальної кількості точок.

## 6. Експорт

Додати експорт у:

- CSV;
- JSON.

---

# ФАЗА 3.1 — HISTORICAL BACKTESTING ENGINE

Фаза 3 дає статистику по вже зібраних даних. Але перед тим, як переходити до Paper Trading (Фаза 4), варто мати змогу "програти" історичні дані заново з різними параметрами стратегії — це дешевше й швидше, ніж чекати тижнями на testnet.

1. Взяти історичні `quotes_1s` / `spread_snapshots` за обраний період.
2. Прогнати через ту саму логіку Spread Engine, що працює в live (не дублювати формули окремим кодом — інакше backtest і live розійдуться).
3. Дозволити змінювати параметри заднім числом для експерименту:
   - поріг спреду;
   - мінімальну тривалість сигналу;
   - комісії (щоб оцінити чутливість до зміни VIP-рівня);
   - мінімальний обсяг.
4. Порахувати симульований PnL за період з урахуванням комісій (без VWAP/slippage на цьому етапі — це вже Фаза 4).
5. Явно позначити результат як **оптимістичну оцінку**: backtest не враховує slippage, latency виконання і конкуренцію з іншими ботами — реальний результат майже завжди гірший.
6. Не оптимізувати параметри стратегії "під" історичні дані настільки, щоб вони ідеально пасували минулому (overfitting) — перевіряти на окремому, не використаному в оптимізації періоді (out-of-sample).

---

# ФАЗА 4 — PAPER TRADING І СИМУЛЯЦІЯ

## 1. Повний Order Book

Підтримувати кілька рівнів стакана, а не тільки best bid/ask.

Для кожної біржі:

- отримувати snapshot;
- застосовувати delta updates;
- перевіряти sequence;
- перебудовувати стакан після розриву sequence.

## 2. VWAP

Для заданого обсягу розраховувати:

- VWAP покупки;
- VWAP продажу;
- реальний executable quantity;
- реальний executable notional.

## 3. Slippage

Розраховувати:

- slippage покупки;
- slippage продажу;
- загальний вплив slippage;
- Net Spread після slippage.

## 4. Торгові обмеження

Враховувати:

- minimum order quantity;
- minimum notional;
- tick size;
- step size;
- price precision;
- quantity precision;
- доступний баланс;
- зарезервовані кошти;
- rate limits.

## 5. Paper Trading Engine

Симулювати:

- створення двох ордерів;
- часткове виконання;
- затримку між ордерами;
- slippage;
- відхилення ордера;
- timeout;
- скасування;
- різні fill prices;
- комісії;
- PnL.

## 6. Testnet / Sandbox

Перевірити:

- створення ордера;
- отримання статусу;
- часткове виконання;
- скасування;
- retry policy;
- idempotency;
- поведінку при reconnect.

---

# ФАЗА 4.1 — МОДЕЛЬ КАПІТАЛУ

1. Капітал заздалегідь розподілений між біржами.
2. Не виконувати withdraw під кожну угоду.
3. Купівля на біржі A і продаж на біржі B виконуються за рахунок уже наявних балансів.
4. Ребалансування між біржами — окремий процес.
5. Моніторити баланс:
   - base asset;
   - quote asset;
   - locked balance;
   - available balance.
6. Якщо балансу недостатньо, відповідний напрямок тимчасово вимикається.
7. Додати target allocation для кожної біржі.
8. Додати сигнал про необхідність ребалансування.
9. Спочатку ребалансування повинно бути ручним.
10. Автоматичне ребалансування розглядати лише після стабільної роботи execution layer.

---

# ФАЗА 5 — EXECUTION LAYER

Цю фазу запускати лише після тижнів стабільної роботи live monitor, історії, аналітики та paper trading.

## 5.1 Manual Execution

1. Кнопка Execute у UI.
2. Обов'язкове підтвердження користувача.
3. Перед підтвердженням показати:
   - біржу купівлі;
   - біржу продажу;
   - обсяг;
   - поточні ціни;
   - очікувані комісії;
   - очікуваний slippage;
   - очікуваний прибуток;
   - вік котирувань.
4. Перед відправленням повторно перевірити котирування.
5. Не виконувати операцію, якщо умови змінилися більше дозволеного порогу.

## 5.2 Semi-Automatic Execution

1. Система готує угоду автоматично.
2. Людина підтверджує виконання.
3. Додати короткий expiry для prepared trade.
4. Після expiry потрібен новий розрахунок.

## 5.3 Fully Automatic Execution

Розглядати лише після стабільної роботи попередніх режимів.

Потрібні:

- idempotency keys;
- order state machine;
- retry policy;
- reconciliation;
- partial fill handling;
- hedge logic;
- emergency stop;
- audit log.

---

# ФАЗА 5.1 — RISK MANAGER

1. Максимальна сума на одну угоду.
2. Максимальний денний оборот.
3. Максимальний денний збиток.
4. Максимальна кількість відкритих операцій.
5. Максимальний exposure на одну біржу.
6. Максимальний exposure на один актив.
7. Мінімальний Net Spread.
8. Мінімальна тривалість сигналу.
9. Максимальний quote age.
10. Максимальна різниця часу між біржами.
11. Автостоп при аномальному русі ціни.
12. Автостоп при втраті WebSocket-з'єднання.
13. Автостоп при втраті синхронізації часу.
14. Автостоп при перевищенні API error rate.
15. Автостоп при невідповідності локального і біржового стану ордерів.
16. Kill Switch:
    - кнопка в UI;
    - API-команда;
    - локальна команда;
    - можливість вимкнути всі нові операції.

---

# ФАЗА 6 — СПОВІЩЕННЯ

Додати канали:

- Telegram;
- Discord;
- Email;
- Webhook.

Типи повідомлень:

- знайдено spread opportunity;
- спред перевищив поріг;
- opportunity тримається довше заданого часу;
- біржа offline;
- reconnect failed;
- stale data;
- queue overflow;
- database error;
- недостатній баланс;
- потрібне ребалансування;
- execution failed;
- partial fill;
- risk limit triggered;
- kill switch activated.

Додати cooldown і deduplication, щоб не створювати spam.

---

# ФАЗА 7 — ЛОГУВАННЯ І МОНІТОРИНГ

## Логування

Використовувати structured JSON logging.

Типи логів:

- Application Logs;
- Exchange Logs;
- WebSocket Logs;
- Spread Engine Logs;
- Database Logs;
- Performance Logs;
- Execution Logs;
- Risk Logs;
- Security Logs.

Додати:

- rotating logs;
- log levels;
- correlation ID;
- request ID;
- trade ID;
- order ID;
- environment name.

## Health Endpoints

Створити:

```text
/health
/health/live
/health/ready
/metrics
```

Health response повинен показувати:

- стан застосунку;
- стан кожної біржі;
- час останнього повідомлення;
- стан БД;
- розмір Queue;
- dropped records;
- clock drift;
- версію застосунку.

## Metrics

Додати Prometheus metrics:

- websocket_connected;
- websocket_reconnect_total;
- websocket_message_rate;
- quote_age_ms;
- spread_calculation_latency;
- frontend_push_rate;
- db_queue_size;
- db_write_latency;
- dropped_records_total;
- api_error_total;
- order_execution_latency;
- risk_rejection_total.

Для візуалізації можна використовувати Grafana.

---

# ФАЗА 8 — ЯКІСТЬ КОДУ

Використовувати:

- Ruff;
- Black;
- mypy;
- pytest;
- pre-commit.

Додати правила:

- обов'язкова типізація критичної бізнес-логіки;
- заборона float у фінансових моделях;
- перевірка форматування;
- перевірка імпортів;
- перевірка security issues;
- мінімальне покриття тестами: **90%+ для Spread Engine і Risk Manager**, 70%+ для решти бізнес-логіки; CI блокує merge при падінні нижче порогу.

---

# ФАЗА 9 — ТЕСТУВАННЯ

## Unit Tests

Перевірити:

- нормалізацію даних;
- spread engine;
- fee calculation;
- stale detection;
- timestamp comparison;
- Decimal rounding;
- threshold event detection;
- risk rules;
- balance checks;
- VWAP;
- slippage.

## Integration Tests

Додати:

- Mock Exchange;
- WebSocket Tests;
- Reconnect Tests;
- Snapshot/Delta Tests;
- Database Tests;
- API Tests;
- WebSocket API Tests;
- Queue Overflow Tests;
- Paper Trading Tests;
- Execution State Machine Tests.

## Load Tests

Перевірити:

- 10 пар;
- 100 пар;
- високий message rate;
- повільну БД;
- повільного frontend-клієнта;
- reconnect усіх бірж одночасно;
- queue overflow;
- memory growth.

## Failure Tests

Симулювати:

- падіння біржі;
- втрату інтернету;
- некоректний snapshot;
- пропущений sequence;
- stale data;
- падіння PostgreSQL;
- переповнення диска;
- неправильний час на сервері;
- часткове виконання одного ордера;
- відмову другого ордера.

---

# ФАЗА 10 — DOCKER І ЛОКАЛЬНИЙ ЗАПУСК

Використовувати:

- Docker;
- Docker Compose.

Контейнери:

- backend;
- frontend;
- PostgreSQL;
- TimescaleDB або звичайний PostgreSQL;
- Redis — тільки якщо реально потрібен;
- Prometheus;
- Grafana.

Команда запуску:

```bash
docker compose up --build
```

Не додавати Redis тільки для вигляду. Для першого MVP in-memory cache достатній, якщо FastAPI працює в одному процесі.

Redis, NATS або Kafka додавати під час масштабування, коли з'являються окремі collectors, workers або кілька API instances.

---

# ФАЗА 11 — CI/CD

Використовувати GitHub Actions.

Pipeline:

1. Install dependencies.
2. Ruff check.
3. Black check.
4. mypy.
5. pytest.
6. Integration tests.
7. Build backend image.
8. Build frontend image.
9. Security scan.
10. Deployment to staging.

Для production deployment потрібне окреме ручне підтвердження.

---

# ФАЗА 12 — ДОКУМЕНТАЦІЯ

Створити:

- README;
- Architecture Diagram;
- API Documentation;
- WebSocket Protocol Documentation;
- Database Schema;
- Deployment Guide;
- Developer Guide;
- Exchange Adapter Guide;
- Risk Management Guide;
- Incident Response Guide.

README повинен містити:

- опис проєкту;
- вимоги;
- запуск;
- конфігурацію;
- тестування;
- структуру папок;
- обмеження MVP;
- правила безпеки.

---

# РЕКОМЕНДОВАНА АРХІТЕКТУРА MVP

```text
Exchange WebSockets
        │
        ▼
Exchange Adapters
(reconnect, heartbeat, snapshot/delta, sequence check)
        │
        ▼
Normalizer
        │
        ▼
Quote Cache
(freshness check, one FastAPI process)
        │
        ├────────────► Health Monitor
        │
        ▼
Spread Engine
(Decimal, fees, volume, both directions, unit-tested)
        │
        ├────────────► FastAPI WebSocket
        │                    │
        │                    ▼
        │              React Dashboard
        │
        └────────────► Bounded Async Queue
                             │
                             ▼
                       PostgreSQL
                             │
                             ▼
                 Retention / Aggregation
```

---

# РЕКОМЕНДОВАНА АРХІТЕКТУРА ПІСЛЯ МАСШТАБУВАННЯ

```text
Exchange WebSockets
        │
        ▼
Independent Collectors
        │
        ▼
Redis Streams / NATS / Kafka
        │
        ├────────────► Quote Processor
        │
        ├────────────► Spread Engine
        │
        ├────────────► Database Writer
        │
        ├────────────► Analytics Worker
        │
        └────────────► WebSocket Gateway
                              │
                              ▼
                        React Dashboard
```

---

# ВАЖЛИВІ НАСКРІЗНІ ПРАВИЛА

- Використовувати Decimal для всіх фінансових розрахунків.
- Не використовувати float для цін, кількості, комісій і PnL.
- Не порівнювати Spot і Futures між собою.
- Завжди чітко визначати buy exchange і sell exchange.
- Завжди рахувати обидва напрямки.
- Завжди враховувати taker fees для реалістичної оцінки.
- Враховувати доступний обсяг у стакані.
- Перевіряти quote age і timestamp difference.
- Не використовувати stale data.
- Не блокувати market data collectors записом у БД.
- Використовувати bounded Queue.
- Не відправляти кожен tick на frontend.
- Для MVP використовувати один FastAPI process.
- Не додавати зайву інфраструктуру до появи реальної потреби.
- API-ключі не повинні мати права withdraw.
- Критична фінансова логіка повинна бути покрита тестами.
- Paper trading обов'язковий перед реальними ордерами.
- Ручний режим повинен з'явитися раніше за автоматичний.
- Kill Switch повинен бути реалізований до production trading.
- Капітал повинен бути заздалегідь розподілений між біржами.
- Не розраховувати на переказ коштів під кожну арбітражну угоду.
- Усі розрахунки повинні мати calculation_version.
- Усі торгові дії повинні мати audit log.

---

# ЧЕКЛИСТ ПЕРЕД ПЕРЕХОДОМ ДО НАСТУПНОЇ ФАЗИ

## Фаза 0 → Фаза 1

- Обрано Spot.
- Обрано 5–10 пар.
- Підготовлено symbol mapping.
- Перевірено API і WebSocket канали.
- Налаштовано NTP.
- Підготовлено конфігурацію.
- API-ключі без withdraw.
- ToS кожної біржі перевірено щодо автоматизованої торгівлі.

## Фаза 1 → Фаза 2

- Усі адаптери стабільно reconnect.
- Snapshot/delta працюють коректно.
- Spread Engine покритий unit tests.
- Stale data не потрапляє в сигнали.
- Dashboard стабільно працює кілька днів.
- Немає неконтрольованого memory growth.

## Фаза 2 → Фаза 3

- Запис у БД не блокує WebSocket collectors.
- Queue не переповнюється під нормальним навантаженням.
- Політика overflow перевірена.
- Retention policy працює.
- DB write latency контролюється.
- Тестове відновлення з бекапу пройдено успішно.

## Фаза 3 → Фаза 4

- Є реальна статистика spread events.
- Відомо, як довго живуть можливості.
- Відомий доступний обсяг.
- Є downsampling.
- Аналітика не базується на stale data.

## Фаза 4 → Фаза 5

- Paper Trading враховує VWAP, slippage і fees.
- Симуляція підтримує partial fills.
- Testnet працює стабільно.
- Результати позитивні протягом тижнів, а не кількох днів.
- Risk Manager протестований.
- Kill Switch протестований.

## Фаза 5 → Fully Automatic

- Manual Execution стабільний.
- Semi-Automatic Execution стабільний.
- Reconciliation працює.
- Часткові виконання обробляються.
- Усі дії мають audit log.
- Ліміти ризику неможливо обійти.
- Проведено failure і load testing.

---

# КІНЦЕВА НАЗВА ПРОЄКТУ

Рекомендована загальна назва:

```text
Crypto Arbitrage Platform
```

Основні модулі:

- Spread Monitor;
- Market Data Collector;
- Analytics;
- Paper Trading;
- Execution Layer;
- Risk Manager;
- Capital Manager;
- Monitoring;
- Notifications.

На першому етапі в UI та документації варто чітко вказувати:

```text
Spread Monitor MVP
```

Це точніше, ніж називати першу версію повноцінним Arbitrage Bot.

---

# ФІНАЛЬНИЙ ПОРЯДОК РОЗРОБКИ

1. Підготовка і безпека.
2. Конфігурація і структура проєкту.
3. Binance Adapter.
4. Bybit Adapter.
5. OKX Adapter.
6. Normalizer.
7. Quote Cache.
8. Freshness Check.
9. Spread Engine.
10. Unit Tests.
11. FastAPI WebSocket.
12. React Dashboard.
13. PostgreSQL.
14. Async Queue і Batch Insert.
15. Retention і Aggregation.
16. Backup і Disaster Recovery.
17. Analytics API.
18. Charts і CSV Export.
19. Historical Backtesting Engine.
20. Full Order Book.
21. VWAP і Slippage.
22. Paper Trading.
23. Capital Model.
24. Risk Manager.
25. Manual Execution.
26. Semi-Automatic Execution.
27. Notifications.
28. Monitoring і Metrics.
29. Integration Tests.
30. Load Tests.
31. Testnet.
32. Лише після цього — обережний розгляд Fully Automatic Execution.
