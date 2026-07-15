# Crypto Arbitrage Platform — Spread Monitor MVP

Модульна платформа для моніторингу міжбіржових спредів (Binance / Bybit / OKX,
тільки Spot). На поточному етапі це **Spread Monitor**, а не торговий бот.

Повний план розробки: [docs/PLAN.md](docs/PLAN.md).
Статус фаз: [CLAUDE.md](CLAUDE.md). Виконано: Фази 0, 0.1, 0.2, 0.3, 1, 2, 2.1.

## Вимоги

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (або pip)
- PostgreSQL 15+ (з Фази 2)
- Node.js 20+ (frontend, з Фази 1)

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
docs/       PLAN.md, фазові документи, безпека
backend/migrations/  Alembic (жодних ручних ALTER TABLE)
```

## Обмеження MVP

- Тільки Spot; Futures не підтримуються і не порівнюються зі Spot.
- Тільки моніторинг: жодного виконання угод (execution — Фаза 5, після
  paper trading).
- Top-of-book (best bid/ask); повний стакан — Фаза 4.
- Один процес FastAPI; Redis/Kafka — лише при масштабуванні.
- Історія: один snapshot котирувань за секунду + закриті spread events;
  сирі тики не зберігаються. Retention/backup — Фази 2.1–2.2.

## Правила безпеки

- API-ключі: тільки read, IP whitelist, ніколи withdraw, окремі ключі на
  середовище, ротація 90 днів — [docs/security/key-rotation-policy.md](docs/security/key-rotation-policy.md).
- Секрети не потрапляють у код, Git, БД у відкритому вигляді та логи
  (маскування увімкнене примусово в production).
- Усі фінансові розрахунки — `Decimal`, float заборонений.
