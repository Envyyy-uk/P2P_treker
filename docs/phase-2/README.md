# Фаза 2 — Збереження історії: що зроблено

| Компонент плану | Реалізація |
|-----------------|------------|
| PostgreSQL | `docker-compose.yml` (мінімальний, тільки Postgres для dev); `DATABASE__DSN` у конфізі |
| Основні таблиці | `app/database/models.py`: `Quote1s` (`quotes_1s`), `SpreadEvent` (`spread_events`) — усі фінансові поля `Numeric(38,18)`, timestamps epoch ms |
| Alembic-міграція | `backend/migrations/versions/c151c86d6651_*.py` — створення обох таблиць + індекси; перевірено upgrade/downgrade roundtrip проти реального Postgres |
| Async Queue | `app/database/writer.py` (`DbWriter`): `asyncio.Queue(maxsize=write_queue_size)`, політики переповнення `drop_oldest` / `drop_newest` / `block` (конфігурується, live-collectors за замовчуванням `drop_oldest`) |
| Batch Insert | `DbWriter._collect_batch`: набір батчу за `batch_max_rows` АБО `batch_max_interval_ms`, що спрацює першим; один батч = одна транзакція (`MarketDataRepository.bulk_insert`) |
| Стратегія збереження | `app/services/history_recorder.py` (`HistoryRecorder`): варіант 1+3 з плану — один snapshot котирувань за секунду (`quotes_1s`) + запис тільки закритих spread events (`spread_events`), сирі тики не зберігаються |
| Spread Event detection | `app/spread/events.py` (`SpreadEventTracker`): подія починається при перетині порогу знизу вгору (валідний net_spread ≥ threshold), закінчується при падінні нижче порогу/невалідності/зникненні напрямку; трекає start/max/average spread і пікові обсяг+прибуток |
| `calculation_version` | Кожен `SpreadRow` і, відповідно, кожен spread event несе `calculation_version` з `app/spread/formulas.py`; **ніколи не перераховується заднім числом** — зміна формули лише інкрементує версію для нових подій |
| Graceful shutdown flush | `HistoryRecorder.stop()` закриває всі відкриті spread events поточним часом; `DbWriter.stop()` дописує чергу з таймаутом `shutdown_flush_timeout_s`, при таймауті логує кількість втрачених записів |
| Метрики (частина Фази 2.1) | `/health` → `database.{queue_size, dropped_records_total, written_total, failed_batches, last_batch_size, last_write_latency_ms}` |

## Поведінка при недоступній БД

`DATABASE__ENABLED=false` — застосунок працює без історії (тільки live-моніторинг).
Якщо `enabled=true`, але Postgres недоступний при старті — критична помилка в
логах, `db_writer`/`history_recorder` залишаються `None`, WS/dashboard
продовжують працювати. Це свідоме рішення MVP: збір ринкових даних
важливіший за їх персистентність (план: "запис у БД не повинен блокувати
market data collectors").

## Перевірено в цьому середовищі

- 123 юніт/інтеграційних тести (writer overflow policies, batch by rows/time,
  failed-batch resilience, shutdown flush/timeout, event tracker сценарії,
  repository grouping); ruff, black, mypy strict — чисто.
- Реальний Postgres 16 (локально в sandbox): `alembic upgrade head` /
  `downgrade -1` / `upgrade head` — успішно, схема відповідає моделям.
- End-to-end прогін повного ланцюжка `QuoteCache → SpreadEngine →
  HistoryRecorder → DbWriter → MarketDataRepository` — рядки реально
  з'явились у `quotes_1s` і `spread_events` з коректними Decimal-значеннями.
- Живий запуск застосунку (`uv run uvicorn app.main:app --workers 1`) з
  `DATABASE__ENABLED=true`: `/health` показує `database.status: "ok"`;
  graceful shutdown (SIGTERM) дренує чергу і логує `"DB writer drained and
  stopped"` перед виходом.

## Запуск локально

```bash
docker compose up -d postgres      # або власний Postgres 15+
cd backend
uv run alembic upgrade head        # застосувати схему
uv run uvicorn app.main:app --workers 1
```

## Що залишилось за межами Фази 2 (навмисно)

- Retention policy, партиціонування за датою, downsampling — реалізовано в
  [Фазі 2.1](../phase-2.1/README.md).
- Backup/PITR, тестове відновлення — Фаза 2.2.
- Periodic fee refresh з account/fee endpoint (місце заготовлене:
  `SpreadEngine.update_taker_fee`, `ExchangeConfig.fee_refresh_interval_hours`) —
  буде підключено разом з REST-клієнтами бірж.
