# Фаза 2.1 — Retention і розмір БД: що зроблено

| Компонент плану | Реалізація |
|-----------------|------------|
| Партиціонування за датою | `quotes_1s` — RANGE-партиціонована таблиця (`PARTITION BY RANGE (timestamp)`), денні партиції `quotes_1s_YYYYMMDD` + `quotes_1s_default` як safety-net; міграція `9bd1a8fa90b4` |
| TimescaleDB | Не використано — план позначає її опціональною; нативного партиціонування Postgres достатньо для обсягів MVP |
| Retention policy | `RetentionConfig` (`app/core/config.py`): окремі retention для сирих даних (`raw_retention_days`, дефолт 7д), кожного downsample-рівня (10с/30д, 1хв/180д, 5хв/365д) і `spread_events` (за замовчуванням `None` = зберігати постійно — вища критичність, план 2.1 п.3 / 2.2 п.5) |
| Downsampling 1с/10с/1хв/5хв | `app/services/downsampler.py`: 1с = сирі `quotes_1s`; 10с/1хв/5хв — OHLC-агрегати (`quotes_10s`, `quotes_1m`, `quotes_5m`) прямо з `quotes_1s`, ідемпотентний UPSERT за `(exchange, symbol, market_type, bucket_timestamp)` |
| Автоматичне видалення застарілих партицій | `app/database/partitioning.py` (`PartitionManager.drop_old_partitions`) — видаляє денні партиції повністю старіші за `raw_retention_days`; ніколи не займає `quotes_1s_default` |
| cron / pg_cron | Не pg_cron (менше залежностей у MVP-скоупі, план дозволяє "cron або pg_cron") — фоновий asyncio-job у самому процесі (`app/services/retention_manager.py`), як і `HistoryRecorder` у Фазі 2; інтервал — `maintenance_interval_hours` |
| Метрики | `/health` → `retention.{partitions_created, partitions_dropped, downsampled_rows, rows_deleted, storage_bytes, last_error}`; `database.{queue_size, dropped_records_total, last_batch_size, last_write_latency_ms}` — з Фази 2 |

## Архітектура

`RetentionManager` — оркестратор одного циклу обслуговування (`run_once`):

1. `PartitionManager.ensure_partitions` — створює денні партиції на
   `[сьогодні-1, сьогодні+partition_ahead_days]` (ідемпотентно, `CREATE TABLE
   IF NOT EXISTS`).
2. `PartitionManager.drop_old_partitions` — видаляє партиції старіші за
   `raw_retention_days`.
3. `Downsampler.run` — UPSERT завершених бакетів (з safety margin 5с, щоб не
   агрегувати вікно, яке ще може отримати сирі рядки) у три downsample-таблиці.
4. Видалення застарілих рядків з downsample-таблиць і (якщо задано)
   `spread_events`.
5. Вимірювання розміру кожної таблиці через `pg_total_relation_size`.

Помилка на будь-якому кроці логується (`last_error`) і не валить застосунок —
той самий принцип, що й у `HistoryRecorder`/`DbWriter`.

## Важлива деталь реалізації: `pg_total_relation_size` на партиційованій таблиці

`pg_total_relation_size('quotes_1s')` повертає **0** — batтьківська
partitioned-таблиця не має власного фізичного сховища, дані лежать у
дочірніх партиціях. `RetentionManager._measure_storage` тому явно підсумовує
розмір усіх дочірніх партицій через `pg_inherits` замість наївного виклику
на батьківську таблицю. Перевірено емпірично на реальному Postgres 16.

## Перевірено в цьому середовищі

- 35 нових юніт-тестів (чисті хелпери дат/бакетів без БД; `PartitionManager`,
  `Downsampler`, `RetentionManager` — через фейкові сесії, у стилі Фази 2);
  ruff, black, mypy strict — чисто; 149 тестів у сумі по всьому backend.
- Реальний Postgres 16: `alembic upgrade head` (обидві міграції з нуля) і
  `downgrade -1` / `upgrade head` roundtrip для міграції `9bd1a8fa90b4` —
  успішно, включно з коректним каскадним видаленням усіх партицій при
  `DROP TABLE` на partitioned parent.
- End-to-end: вставка сирих рядків у різні дні → `ensure_partitions` створює
  партиції → `Downsampler.run` агрегує їх у `quotes_10s/1m/5m` → повторний
  прогін того самого вікна не дублює рядки (UPSERT) → `drop_old_partitions`
  фізично видаляє застарілу партицію → `pg_total_relation_size` по
  `pg_inherits` показує коректний ненульовий розмір `quotes_1s`.
- Живий запуск повного застосунку (`uv run uvicorn app.main:app --workers
  1`) з `DATABASE__ENABLED=true`: при старті `RetentionManager.run_once()`
  реально створив 4 денні партиції в БД (`behind_days=1` + сьогодні +
  `partition_ahead_days=2`), `/health` показав `retention.partitions_created:
  4` і ненульові `storage_bytes`; graceful shutdown відпрацював коректно.

## Операційна примітка

`ensure_partitions` може впасти з `CheckViolationError`, якщо в
`quotes_1s_default` вже лежать рядки, що потрапляють у діапазон нової
партиції (Postgres захищає цілісність даних). У штатному режимі це не
станеться: `RetentionManager` створює партиції на кілька днів наперед і
запускається при кожному старті застосунку до першого запису семплера. Це
може виникнути тільки якщо застосунок довго не запускався і дані писались
би напряму в обхід `ensure_partitions` — не сценарій MVP.

## Що залишилось за межами Фази 2.1 (навмисно)

- Архівування (а не просто видалення) застарілих партицій — план дозволяє
  "видаляти АБО архівувати"; MVP обрав видалення як простіше.
- pg_cron — обрано in-process asyncio job замість зовнішньої залежності.
- Backup/PITR і тестове відновлення — Фаза 2.2.
