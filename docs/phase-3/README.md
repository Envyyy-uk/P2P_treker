# Фаза 3 — Аналітика: що зроблено

Read-only API поверх таблиць з Фаз 2/2.1 (`quotes_1s`/`quotes_10s`/`quotes_1m`/
`quotes_5m`/`spread_events`) — не впливає на live-моніторинг чи запис історії.

| Компонент плану | Реалізація |
|-----------------|------------|
| API Endpoint історії | `GET /api/analytics/quotes` — OHLC-серія котирувань однієї біржі; параметри symbol, exchange, market_type, from/to, interval |
| Threshold Events | `GET /api/analytics/spread-events` — список подій з `spread_events` (Фаза 2); визначення start/end/duration незмінне з детектора Фази 2 |
| Статистика | `GET /api/analytics/spread-events/stats` — count, total/avg/median/max duration, avg/max net spread, avg обсяг, avg прибуток, % подій довших за min_duration |
| Фільтри | symbol, buy_exchange, sell_exchange, market_type, from/to, min_net_spread_pct, min_notional, min_duration_ms — на обох ендпоінтах (list і stats) |
| Графіки (Gross/Net Spread, Threshold) | `GET /api/analytics/spread-history` — рахує gross/net spread по історичних close-цінах пари бірж **тією ж формулою**, що й live Spread Engine (`app.spread.formulas`) — одне джерело правди для математики, як вимагає план для backtesting (Фаза 3.1, п.2) |
| Backend-side агрегація/downsampling/обмеження точок | `choose_interval()` автоматично підбирає найдрібніший рівень (1s/10s/1m/5m), що вкладається в `ANALYTICS__MAX_CHART_POINTS` (дефолт 2000); LIMIT+1 виявляє truncation |
| Pagination | `GET /api/analytics/spread-events` — `page`/`page_size`, `page_size` обрізається до `ANALYTICS__MAX_PAGE_SIZE` |
| Експорт CSV/JSON | `GET /api/analytics/spread-events/export?format=csv\|json` — без пагінації, але з `max_rows` cap (50 000) |

## Важливі рішення

- **"Gross/Net Spread over time" рахується на льоту**, а не зберігається
  окремою таблицею `spread_snapshots` — план явно позначає цю таблицю
  опціональною (Фаза 2). Замість дублювання даних `spread-history` бере OHLC
  двох бірж з уже наявних `quotes_1s`/downsample-таблиць і рахує spread
  через `app.spread.formulas` (той самий модуль, що й live Spread Engine).
- **Комісії для історичного spread — поточні з конфігурації**, не історичні
  на кожен момент часу (БД не зберігає комісію посекундно). Це те саме
  спрощення, що план явно допускає для backtesting (Фаза 3.1, п.5:
  результат — оптимістична оцінка, не точна історична реконструкція).
- **`min_duration_ms` — read-side фільтр**, не змінює вже записані
  `spread_events` (версійність, план Фаза 2). За замовчуванням 500мс
  (`ANALYTICS__DEFAULT_MIN_EVENT_DURATION_MS`), як приклад з плану.
- **`pct_meeting_min_duration`** рахується як `qualifying_count / total_count`,
  де `total_count` — усі події за іншими фільтрами (без duration), а
  `qualifying_count` — ті, що пройшли ще й поріг тривалості. Так задум
  плану ("відсоток подій, що тривали довше мінімального часу") не
  суперечить одночасній вимозі "фільтрувати короткі події" — stats
  показують обидва зрізи.
- **Медіана — через `percentile_cont` у Postgres**, не в Python (уникає
  вивантаження всіх рядків у застосунок). Виявлено й виправлено при
  e2e-перевірці: на відміну від `avg()`/`sum()`, `percentile_cont`
  повертає Python `float`, а не `Decimal`, через asyncpg — нормалізовано
  через `Decimal(str(...))` перед поверненням.

## Знайдений і виправлений баг конфігурації (Фаза 2.1)

При першому e2e-прогоні Фази 3 виявилось, що
`RETENTION__SPREAD_EVENTS_RETENTION_DAYS=` (порожньо в `.env.example`,
"означає постійне зберігання") падав з `pydantic.ValidationError` — Pydantic
Settings не парсить порожній env var як `None` для `int | None` за
замовчуванням. Цей баг існував з Фази 2.1 і не проявлявся раніше, бо
попередні e2e-прогони не копіювали `.env.example` буквально в кожному
випадку. Виправлено `field_validator(mode="before")` у `RetentionConfig`,
що трактує порожній рядок як `None`.

## Перевірено в цьому середовищі

- 23 нових тести (9 чистих unit для `choose_interval`/`_row_to_ohlc`, 14
  інтеграційних для routes із fake-репозиторієм — валідація параметрів,
  серіалізація Decimal, 503 коли БД вимкнена); 172 тести в сумі по
  backend; ruff, black, mypy strict — чисто.
- Реальний Postgres 16: засіяно котирування двох бірж (binance/bybit) і
  3 spread events різної тривалості (200мс/1000мс/8000мс). Перевірено:
  - `quote_history`/`spread_history` повертають вирівняні по timestamp
    точки з коректним gross/net spread;
  - `min_duration_ms=500` коректно виключає 200-мс "блип" (3 → 2 події);
  - `spread_event_stats`: `median_duration_ms` між 1000 і 8000 мс дало
    точно 4500 (Decimal), `pct_meeting_min_duration` = 2/3×100;
  - `export_spread_events` повертає всі рядки без пагінації.
- Живий запуск повного застосунку (`uv run uvicorn app.main:app --workers
  1`) з реальним HTTP: усі 5 ендпоінтів (`/quotes`, `/spread-history`,
  `/spread-events`, `/spread-events/stats`, `/spread-events/export`)
  відповіли коректним JSON/CSV; graceful shutdown відпрацював штатно.

## Що залишилось за межами Фази 3 (навмисно)

- Historical Backtesting Engine (прогін стратегії заднім числом із
  варійованими параметрами) — окрема Фаза 3.1.
- Формальні Pydantic response-моделі для OpenAPI-схеми — зараз ендпоінти
  повертають прості dict'и (як `/health`), консистентно з рештою проєкту;
  можна додати пізніше без зміни контракту.
