# Фаза 2.2 — Backup і Disaster Recovery: що зроблено

Backup/DR — операційна задача рівня сервера БД, а не бізнес-логіка
застосунку, тому реалізація тут — набір `ops/`-скриптів + документація
(runbook), а не Python-код усередині FastAPI-процесу.

| Компонент плану | Реалізація |
|-----------------|------------|
| `pg_dump`/WAL-архівування (PITR) | `ops/backup.sh` — `pg_dump --format=custom`; WAL-архівування не додано в MVP (див. "Рекомендації" нижче) |
| Бекапи окремо від сервера БД | `BACKUP_DIR` — env var, у продакшені має вказувати на інший диск/регіон/S3-сумісне сховище (rclone/s3fs змонтований шлях); скрипт агностичний до фактичного сховища |
| RPO / RTO | Визначені й задокументовані нижче |
| Тестове відновлення (не лише перевірка існування файлу) | `ops/verify_backup.sh` — реально відновлює бекап у окрему scratch-БД (`arbitrage_restore_verify`), перевіряє схему і рядки по кожній таблиці, падає з ненульовим exit code, якщо таблиця відсутня |
| `spread_events` вищий пріоритет відновлення | `ops/restore.sh --priority` — трипрохідне відновлення: схема → `spread_events` (стає доступним для запитів найшвидше) → решта таблиць (через TOC-list фільтрацію `pg_restore -l` / `--use-list`, бо `pg_restore` не має `--exclude-table-data`) |
| Incident Response Guide (Фаза 12) | Попередній runbook: [docs/operations/incident-response.md](../operations/incident-response.md) — буде розширений у Фазі 12 повним набором документів |

## RPO / RTO

| Категорія даних | RPO (прийнятна втрата) | Обґрунтування |
|-----------------|------------------------|---------------|
| `spread_events` | ≤ 1 година (при щогодинному бекапі) або менше з WAL-архівуванням | Історичні дані для аналітики/backtesting (Фаза 3.1) — цінність зростає з часом, втрата дорожча |
| `quotes_1s` / `quotes_10s` / `quotes_1m` / `quotes_5m` | ≤ 24 години (щоденний бекап) | Регенерується частково (downsample можна перерахувати з `quotes_1s`); сирі тики — не критичний прод-стан, а моніторингові дані |
| Конфігурація / секрети | N/A — не в БД (`.env` / secrets manager, поза скоупом backup) | Див. `docs/security/key-rotation-policy.md` |

**RTO (Recovery Time Objective):** для обсягів MVP (одна нода PostgreSQL,
десятки–сотні МБ) повне відновлення `pg_restore` займає секунди–хвилини
(перевірено емпірично — див. нижче). З `--priority` `spread_events`
стає доступним для запитів за секунди, навіть якщо повне відновлення
`quotes_1s` ще триває. Формальний RTO для MVP: **≤ 15 хвилин** від моменту
виявлення інциденту до відновленого `spread_events` і працюючого
моніторингу; повне відновлення історії — **≤ 1 година**.

## Розклад бекапів (приклад crontab)

```cron
# Щогодинний бекап (задовольняє RPO spread_events ≤ 1 год)
0 * * * * PGHOST=... PGUSER=... PGPASSWORD=... PGDATABASE=arbitrage \
    BACKUP_DIR=/mnt/backups /path/to/ops/backup.sh >> /var/log/arb-backup.log 2>&1

# Щотижнева перевірка, що останній бекап реально відновлюється
0 3 * * 0 latest=$(ls -t /mnt/backups/arbitrage_*.dump | head -1); \
    PGHOST=... PGUSER=... PGPASSWORD=... /path/to/ops/verify_backup.sh "$latest" \
    >> /var/log/arb-backup-verify.log 2>&1
```

pg_cron не використовується (план дозволяє "cron або pg_cron") — системний
cron простіший і не додає залежностей БД, узгоджено з тим самим рішенням
для Фази 2.1 (in-process job замість pg_cron для retention/downsampling).

## Перевірено в цьому середовищі

Повний disaster recovery drill проти реального Postgres 16:

1. Вставлено тестові дані (`quotes_1s`: 10 рядків, `spread_events`: 1 рядок).
2. `ops/backup.sh` → реальний `.dump`-файл (33.8 KB).
3. `ops/verify_backup.sh` → відновлення в scratch-БД, підтверджені всі
   11 таблиць (включно з денними партиціями `quotes_1s`) і коректні
   лічильники рядків.
4. Симуляція катастрофи: `DROP DATABASE arbitrage` (повна втрата даних).
5. `ops/restore.sh <dump> arbitrage --priority` → схема відновлена,
   `spread_events` доступний одразу, потім решта таблиць — без помилок.
6. Перевірено окремо: `ops/restore.sh <dump> arbitrage` (без `--priority`,
   звичайний однопрохідний `pg_restore --clean`) — так само відновив
   10/1 рядків коректно.
7. Лічильники рядків після відновлення (обидва шляхи) точно збіглися з
   лічильниками до катастрофи: `quotes_1s: 10`, `spread_events: 1`.

## Рекомендації для production (поза скоупом MVP-коду)

- Додати WAL-архівування (`archive_command` + `pg_basebackup`, або
  готовий інструмент — pgBackRest / WAL-G) для near-continuous RPO
  замість щогодинного `pg_dump`, коли обсяг `spread_events` стане
  цінним для backtesting.
- `BACKUP_DIR` — реальне зовнішнє сховище (S3-сумісний бакет), не
  локальна директорія на тому ж диску, що й сама БД.
- Роль для `verify_backup.sh` має мати `CREATEDB` (для scratch-БД) —
  окрема від read/write ролі застосунку (`DATABASE__DSN`), якій це
  право не потрібне і не повинне надаватись.
- Периметр доступу до бекапів — не менш суворий, ніж до самої БД
  (бекап містить ті самі дані).
