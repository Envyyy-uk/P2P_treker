# Incident Response Guide (попередня версія)

> Це попередній runbook, створений разом з Фазою 2.2 (Backup/DR), як того
> вимагає план. Повний набір документів (Architecture Diagram, API/WS
> Protocol, Database Schema, Deployment Guide, Developer Guide, Exchange
> Adapter Guide, Risk Management Guide) — Фаза 12, після появи Execution
> Layer і Risk Manager, про які там теж треба буде написати.

## Втрата даних БД (crash, помилкове видалення, corruption)

1. **Зупинити застосунок**, якщо БД у некоректному стані (щоб не писати
   поверх пошкоджених даних): `systemctl stop spread-monitor` або
   еквівалент.
2. **Оцінити масштаб:** які таблиці/партиції постраждали
   (`psql -c '\dt'`, перевірка логів PostgreSQL).
3. **Знайти найсвіжіший придатний бекап:**
   `ls -t $BACKUP_DIR/arbitrage_*.dump | head -1`.
4. **Відновити з пріоритетом** (`spread_events` — цінніші історичні дані,
   доступні першими):
   ```bash
   ./ops/restore.sh <dump_file> arbitrage --priority
   ```
5. **Перевірити цілісність** після відновлення:
   ```bash
   PGDATABASE=arbitrage psql -c "SELECT count(*) FROM quotes_1s;"
   PGDATABASE=arbitrage psql -c "SELECT count(*) FROM spread_events;"
   ```
6. **Застосувати міграції**, якщо бекап старіший за поточну схему:
   `uv run alembic upgrade head`.
7. **Запустити застосунок**, перевірити `/health` (`database.status`,
   `retention.last_error`).
8. **Задокументувати інцидент:** час втрати даних, причина, тривалість
   простою, обсяг втрачених даних (реальний RPO цього інциденту) — для
   порівняння з цільовим RPO/RTO (`docs/phase-2.2/README.md`) і
   майбутнього audit log (Фаза 5).

## Втрата WebSocket-з'єднання з біржею

Покривається автоматично: `BaseWsAdapter` перепідключається з exponential
backoff (`docs/phase-1/README.md`). Якщо reconnect_count зростає
безперервно — перевірити мережевий доступ до біржі
(`docs/phase-0/exchange-api-check.md`) і статус самої біржі.

## Переповнення async Queue запису в БД

`/health` → `database.dropped_records_total` зростає. Причина — БД не
встигає за потоком або недоступна. Перевірити `database.last_write_latency_ms`
і стан PostgreSQL (`pg_stat_activity`, диск, CPU). Короткочасне
переповнення при `drop_oldest` — очікувана деградація, не інцидент;
стабільне зростання — потребує втручання (масштабування БД чи queue).

## Дрейф системного часу

Старт застосунку падає (`ClockDriftError`), якщо `MONITORING__FAIL_ON_CLOCK_DRIFT=true`
і дрейф перевищує поріг. Перевірити `chronyc tracking` /
`chronyc sources -v` на сервері (`docs/phase-0/ntp-setup.md`).
