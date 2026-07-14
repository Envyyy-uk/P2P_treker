# Crypto Arbitrage Platform (Spread Monitor MVP)

Повний план розробки: [docs/PLAN.md](docs/PLAN.md) — **єдине джерело правди** для фаз,
формул і наскрізних правил. Перед будь-якою зміною звіряйся з ним.

## Статус фаз

- [x] Фаза 0 — Підготовка (ринок, пари, symbol mapping, комісії, freshness, формули, NTP, ToS)
- [x] Фаза 0.1 — Безпека (ключі, .env, маскування секретів, політика ротації)
- [x] Фаза 0.2 — Configuration (Pydantic Settings, валідація при старті)
- [x] Фаза 0.3 — Структура проєкту (backend/frontend scaffold, Alembic)
- [x] Фаза 1 — Live моніторинг (adapters, normalizer, quote cache, spread engine, WS, dashboard)
- [ ] Фаза 2 — Збереження історії (PostgreSQL, async queue, batch insert)
- [ ] Фаза 2+ — див. docs/PLAN.md

## Наскрізні правила (короткий витяг з PLAN.md)

- **Тільки Decimal** для цін, кількостей, комісій, PnL. Ніколи float.
- Тільки Spot для MVP; не змішувати market types.
- Завжди рахувати обидва напрямки (buy A → sell B і buy B → sell A).
- Net spread рахувати за мультиплікативною моделлю з taker fees.
- Не використовувати stale котирування (quote age / timestamp diff пороги в конфігурації).
- MVP працює в одному процесі FastAPI (`--workers 1`).
- API-ключі: тільки read для MVP, ніколи withdraw, не зберігати в коді/Git/логах.
- Усі розрахунки мають `calculation_version`; зміна формули застосовується тільки проспективно.
- Міграції БД — тільки через Alembic.

## Команди

```bash
cd backend
uv sync                     # встановити залежності
uv run pytest               # тести
uv run ruff check app tests # лінт
uv run black --check app tests
uv run mypy app             # типізація
uv run uvicorn app.main:app --workers 1   # запуск (MVP: строго 1 worker)
```

## Структура

- `backend/` — FastAPI застосунок (структура за Фазою 0.3 плану)
- `frontend/` — React dashboard (Фаза 1)
- `docs/` — план, фазові документи, безпека
- `backend/migrations/` — Alembic (жодних ручних ALTER TABLE)
