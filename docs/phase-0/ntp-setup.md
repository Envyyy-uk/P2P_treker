# NTP-синхронізація часу (Фаза 0, п.10–11)

Уся freshness-логіка (quote age, timestamp diff) залежить від коректного
системного часу. Один NTP-сервер — точка відмови, тому конфігуруємо кілька.

## chrony (рекомендовано)

```bash
sudo apt install chrony
```

`/etc/chrony/chrony.conf`:

```text
# Кілька незалежних пулів — жоден не є єдиною точкою відмови
pool time.cloudflare.com iburst
pool time.google.com    iburst
pool pool.ntp.org       iburst
server time.aws.com     iburst

# Дозволити великий initial step тільки на старті
makestep 1.0 3

# Логи для діагностики дрейфу
driftfile /var/lib/chrony/chrony.drift
```

```bash
sudo systemctl enable --now chrony
chronyc tracking      # перевірити offset
chronyc sources -v    # перевірити, що є кілька живих джерел
```

## Перевірка дрейфу при старті застосунку (п.11)

`backend/app/core/time_sync.py` при старті:

1. Запитує кілька NTP-серверів зі списку `MONITORING__NTP_SERVERS`.
2. Бере перший успішний offset (сервери — резерв один одному).
3. Якщо `|offset| > MONITORING__MAX_CLOCK_DRIFT_MS` (дефолт 500 мс) —
   застосунок логує критичну помилку і **відмовляється стартувати**
   (у dev можна пом'якшити через `MONITORING__FAIL_ON_CLOCK_DRIFT=false`).
4. Якщо жоден сервер недоступний — warning (мережа може блокувати UDP/123),
   старт не блокується, але health endpoint покаже `clock_drift: unknown`.
