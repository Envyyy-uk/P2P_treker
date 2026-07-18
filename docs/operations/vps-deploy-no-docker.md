# Розгортання на VPS без Docker (backend 24/7 + PWA на iPhone)

Цей runbook — альтернатива `docker-compose.yml` для тих, кому Docker
на конкретному хості нестабільний. Усі компоненти (PostgreSQL, backend,
frontend, reverse proxy) встановлюються нативно через пакетний менеджер
ОС і керуються `systemd`. Перевірено на Ubuntu/Debian; для інших
дистрибутивів — ті самі кроки, інші назви пакетів.

Результат: `https://your-domain.example` доступний 24/7, HTTPS
автоматично (Let's Encrypt через Caddy) — необхідна умова, щоб iPhone
Safari дав "Додати на екран Домівки" з робочим service worker
(PWA вимагає secure context, окрім localhost).

## 0. Вимоги

- VPS з публічною IP (Ubuntu 22.04+/Debian 12+), root або sudo доступ.
- Домен (навіть безкоштовний з DuckDNS/Cloudflare), A-запис → IP VPS.
  Без домена Let's Encrypt не видасть сертифікат — можна тимчасово
  користуватись http:// за IP, але тоді PWA/service worker не запрацює
  на iPhone (Safari вимагає HTTPS поза localhost).

## 1. PostgreSQL (нативно, без Docker)

```bash
sudo apt update && sudo apt install -y postgresql
sudo -u postgres psql -c "CREATE USER arb WITH PASSWORD 'СИЛЬНИЙ_ПАРОЛЬ';"
sudo -u postgres psql -c "CREATE DATABASE arbitrage OWNER arb;"
```

Замініть `СИЛЬНИЙ_ПАРОЛЬ` на реальний секрет — той самий піде в `.env`
backend'у нижче. Ніколи не використовуйте дефолтний `arb`/`arb` з
локальної розробки на публічному VPS.

## 2. Системний користувач і код застосунку

```bash
sudo useradd --system --home /opt/spread-monitor --shell /usr/sbin/nologin spread-monitor
sudo mkdir -p /opt/spread-monitor
sudo git clone <URL_РЕПОЗИТОРІЮ> /opt/spread-monitor
sudo chown -R spread-monitor:spread-monitor /opt/spread-monitor
```

## 3. Backend

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo -u spread-monitor sh
cd /opt/spread-monitor/backend
sudo -u spread-monitor cp .env.example .env
sudo -u spread-monitor nano .env   # DATABASE__DSN з паролем із кроку 1,
                                    # ENVIRONMENT=production,
                                    # LOGGING__MASK_SECRETS=true (обов'язково для prod)
sudo -u spread-monitor /home/spread-monitor/.local/bin/uv sync
sudo -u spread-monitor /home/spread-monitor/.local/bin/uv run alembic upgrade head
```

`ENVIRONMENT=production` вмикає перевірку конфігурації (`Settings._validate`
у `app/core/config.py`): застосунок відмовиться стартувати, якщо
`LOGGING__MASK_SECRETS=false` — секрети в логах на prod заборонені
(план, Фаза 0.1).

### systemd unit

```bash
sudo cp /opt/spread-monitor/ops/systemd/spread-monitor-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spread-monitor-backend
sudo systemctl status spread-monitor-backend   # має бути active (running)
journalctl -u spread-monitor-backend -f        # живі логи
```

Backend слухає лише `127.0.0.1:8000` (unit вже так налаштований) —
назовні його порт не відкривається, увесь зовнішній трафік іде через
reverse proxy (крок 5).

## 4. Frontend (збірка один раз, статичні файли)

```bash
cd /opt/spread-monitor/frontend
sudo apt install -y nodejs npm   # або nvm для конкретної версії Node 20+
sudo -u spread-monitor npm ci
sudo -u spread-monitor npm run build   # -> dist/, включно з manifest/sw.js/іконками PWA
```

`npm run build` треба перезапускати після кожного оновлення frontend-коду
(`git pull` + `npm run build`) — на відміну від backend, тут немає
watch-режиму в проді.

## 5. Caddy (reverse proxy + автоматичний HTTPS)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo cp /opt/spread-monitor/ops/systemd/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile   # замінити your-domain.example на реальний домен
sudo systemctl restart caddy
sudo systemctl status caddy
```

Caddy сам випустить і оновлюватиме Let's Encrypt сертифікат для домену з
Caddyfile — жодних ручних `certbot` кроків.

Перевірка: `curl -I https://your-domain.example/health` має повернути
`200` з реального backend через проксі.

## 6. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

Порт 8000 (backend) і 5432 (Postgres) НЕ відкриваються назовні —
доступ лише через `127.0.0.1` (backend вже так налаштований; для
Postgres за замовчуванням `listen_addresses = 'localhost'` — не чіпати).

## 7. iPhone: встановити як "програму" (PWA)

1. Відкрити `https://your-domain.example` в Safari на iPhone.
2. Кнопка "Поділитися" (квадрат зі стрілкою вгору) → **"На екран Домівки"**.
3. З'явиться іконка застосунку (той самий `manifest.webmanifest` +
   `apple-touch-icon.png`, зроблені у Фазі PWA frontend) — відкривається
   без адресного рядка Safari, як звичайна програма.

## 8. Оновлення після змін коду

```bash
cd /opt/spread-monitor && sudo -u spread-monitor git pull
cd backend && sudo -u spread-monitor /home/spread-monitor/.local/bin/uv sync \
  && sudo -u spread-monitor /home/spread-monitor/.local/bin/uv run alembic upgrade head
sudo systemctl restart spread-monitor-backend
cd ../frontend && sudo -u spread-monitor npm ci && sudo -u spread-monitor npm run build
```

Caddy й systemd переживають перезавантаження VPS автоматично
(`enable` у кроці 3 і стандартний Caddy-пакет уже вмикають автостарт).

## Обмеження цього підходу

- Один VPS = єдина точка відмови (як і локальний запуск); backup/DR —
  той самий `ops/backup.sh`/`ops/restore.sh` (Фаза 2.2), просто скрипти
  запускаються на VPS замість локальної машини.
- iOS web push (через PWA) підтримується з iOS 16.4+, але вимагає
  окремої інтеграції (VAPID-ключі, Push API) — не покрито цим
  документом; Фаза 6 плану (Сповіщення: Telegram/Discord/Email/Webhook)
  лишається основним каналом сповіщень.
