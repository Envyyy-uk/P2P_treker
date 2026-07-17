# Crypto Arbitrage Platform — Spread Monitor MVP

Модульна платформа для моніторингу міжбіржових спредів (Binance / Bybit / OKX,
тільки Spot). На поточному етапі це **Spread Monitor**, а не торговий бот.

Повний план розробки: [docs/PLAN.md](docs/PLAN.md).
Статус фаз: [CLAUDE.md](CLAUDE.md). Виконано: Фази 0, 0.1, 0.2, 0.3, 1, 2, 2.1, 2.2, 3, 3.1, 4, 4.1.

## Вимоги

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (або pip)
- PostgreSQL 15+ (з Фази 2)
- Node.js 20+ (frontend, з Фази 1)
- `pg_dump`/`pg_restore`/`createdb`/`dropdb` (пакет `postgresql-client`) — для `ops/` (Фаза 2.2)

## Запуск (backend)

```bash
docker compose up -d postgres      # локальна PostgreSQL для історії (Фаза 2)
cd backend
cp .env.example .env        # заповнити своїми значеннями
uv sync
uv run alembic upgrade head        # застосувати схему БД
uv run uvicorn app.main:app --workers 1
```

⚠️ **Строго один worker** для MVP: quote cache живе в пам'яті процесу,
кілька workers матимуть розсинхронізовані копії (див. PLAN.md, Фаза 1, п.4).

Без PostgreSQL: встановіть `DATABASE__ENABLED=false` у `.env` — live-моніторинг
працюватиме, історія не писатиметься.

Перевірка: `curl localhost:8000/health`

## Тестування

```bash
cd backend
uv run pytest                          # усі тести
uv run pytest tests/unit               # тільки юніт
uv run ruff check app tests            # лінт
uv run black --check app tests         # формат
uv run mypy app                        # типи
```

## Конфігурація

Уся конфігурація — через env-змінні / `.env` (Pydantic Settings, валідація при
старті). Секції та всі параметри — у [backend/.env.example](backend/.env.example).
Вкладені поля: `SECTION__FIELD`, напр. `TRADING__MAX_QUOTE_AGE_MS=1000`.

## Структура

```text
backend/    FastAPI застосунок (app/core, app/exchanges, app/spread, ...)
frontend/   React dashboard (Фаза 1)
docs/       PLAN.md, фазові документи, безпека, операційні runbook'и
backend/migrations/  Alembic (жодних ручних ALTER TABLE)
ops/        backup.sh / restore.sh / verify_backup.sh (Фаза 2.2)
```

## Обмеження MVP

- Тільки Spot; Futures не підтримуються і не порівнюються зі Spot.
- Тільки моніторинг + paper trading (in-memory симуляція): жодного
  реального виконання угод на біржі (execution — Фаза 5).
- Повний Order Book є (Фаза 4, generic snapshot/delta engine), але без
  live WS depth-адаптерів для конкретних бірж — рівні стакану передаються
  в тілі запиту Paper Trading API, а не тягнуться з live-фіда.
- Один процес FastAPI; Redis/Kafka — лише при масштабуванні.
- Історія: один snapshot котирувань за секунду + закриті spread events;
  сирі тики не зберігаються. Retention — Фаза 2.1, backup/restore —
  [ops/](ops/) і [docs/phase-2.2](docs/phase-2.2/README.md).

## Backup і Disaster Recovery (Фаза 2.2)

```bash
PGHOST=localhost PGUSER=arb PGPASSWORD=arb PGDATABASE=arbitrage \
    BACKUP_DIR=/mnt/backups ./ops/backup.sh          # бекап

./ops/verify_backup.sh /mnt/backups/arbitrage_*.dump # тестове відновлення

./ops/restore.sh <dump_file> arbitrage --priority    # DR: spread_events першими
```

RPO/RTO, розклад cron, повний runbook — [docs/phase-2.2/README.md](docs/phase-2.2/README.md),
[docs/operations/incident-response.md](docs/operations/incident-response.md).

## Analytics API (Фаза 3)

```text
GET /api/analytics/quotes            OHLC-історія котирувань однієї біржі
GET /api/analytics/spread-history    Gross/Net spread пари бірж у часі
GET /api/analytics/spread-events     список threshold events (фільтри, пагінація)
GET /api/analytics/spread-events/stats    статистика (duration, spread, обсяг, прибуток)
GET /api/analytics/spread-events/export   CSV/JSON експорт
```

Деталі, обмеження, знайдені під час перевірки нюанси —
[docs/phase-3/README.md](docs/phase-3/README.md).

## Historical Backtesting (Фаза 3.1)

```bash
curl -X POST localhost:8000/api/backtest/run -H "Content-Type: application/json" -d '{
  "symbols": ["BTC-USDT"], "from": 1784246400000, "to": 1784246430000,
  "spread_threshold": "0.002", "min_duration_ms": 500
}'
```

Прогонює історію через ту саму логіку `SpreadEngine`/`SpreadEventTracker`,
що й live; параметри (поріг, тривалість, комісії, обсяг) можна міняти
заднім числом для експерименту. Результат — оптимістична оцінка (без
VWAP/slippage/затримки виконання). Деталі —
[docs/phase-3.1/README.md](docs/phase-3.1/README.md).

## Paper Trading (Фаза 4)

```bash
curl -X POST localhost:8000/api/paper-trading/execute -H "Content-Type: application/json" -d '{
  "symbol": "BTC-USDT", "buy_exchange": "binance", "sell_exchange": "bybit",
  "quantity": "1",
  "buy_book": {"bids": [], "asks": [{"price": "100", "quantity": "10"}]},
  "sell_book": {"bids": [{"price": "102", "quantity": "10"}], "asks": []}
}'

curl localhost:8000/api/paper-trading/balances
curl -X POST localhost:8000/api/paper-trading/balances -H "Content-Type: application/json" \
  -d '{"exchange": "binance", "asset": "USDT", "total": "5000"}'
```

Повністю in-memory симуляція двоногого арбітражу: реальний Order Book
(snapshot/delta, sequence gap detection), VWAP-заповнення, slippage,
торгові обмеження (min qty/notional, tick/step), баланс (available/
locked), rate limit, часткові виконання, timeout, cancellation. Не
залежить від БД. Плюс окремий `BinanceTestnetClient`
(`app/testnet/binance.py`) з retry policy (backoff тільки на 5xx/мережеві
помилки, ніколи на 4xx) і ідемпотентністю за `client_order_id`. Деталі,
що свідомо не реалізовано (live WS depth-адаптери) і чому —
[docs/phase-4/README.md](docs/phase-4/README.md).

## Модель капіталу (Фаза 4.1)

```bash
curl localhost:8000/api/capital/status
curl localhost:8000/api/capital/rebalance-signals
curl -X POST localhost:8000/api/capital/transfer -H "Content-Type: application/json" \
  -d '{"asset": "USDT", "from_exchange": "bybit", "to_exchange": "binance", "amount": "500"}'
```

Моніторинг балансу (base/quote, available/locked) по біржах поверх того
самого `BalanceManager`, що й Paper Trading; target allocation і сигнал
ребалансування (`CAPITAL__TARGET_ALLOCATION`); ребалансування лише
ручне — `POST /transfer` тільки фіксує в обліку переказ, який оператор
уже виконав на реальних біржах, жодного автоматичного переказу коштів.
Деталі — [docs/phase-4.1/README.md](docs/phase-4.1/README.md).

## Правила безпеки

- API-ключі: тільки read, IP whitelist, ніколи withdraw, окремі ключі на
  середовище, ротація 90 днів — [docs/security/key-rotation-policy.md](docs/security/key-rotation-policy.md).
- Секрети не потрапляють у код, Git, БД у відкритому вигляді та логи
  (маскування увімкнене примусово в production).
- Усі фінансові розрахунки — `Decimal`, float заборонений.
