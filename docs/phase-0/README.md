# Фаза 0 — Підготовка: чеклист виконання

Статус кожного пункту Фази 0 з [PLAN.md](../PLAN.md).

| # | Пункт | Статус | Де реалізовано |
|---|-------|--------|----------------|
| 1 | Тип ринку для MVP — тільки Spot | ✅ | `backend/app/models/enums.py` (`MarketType.SPOT`), конфігурація дозволяє тільки spot |
| 2 | 5 торгових пар | ✅ | BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT — `backend/app/core/symbols.py` |
| 3 | Таблиця відповідності символів | ✅ | `backend/app/core/symbols.py` (`SYMBOL_MAP`) + тести |
| 4 | Не змішувати типи ринку | ✅ | `market_type` — обов'язкове поле моделі котирування; порівняння різних типів заборонене на рівні формул |
| 5 | Комісії бірж + періодичне оновлення | ✅ | Дефолтні taker/maker у `.env.example` / `ExchangeConfig`; `fee_refresh_interval_hours` для оновлення через account/fee endpoint (реалізація fetch — Фаза 1) |
| 6 | Максимальний вік котирування | ✅ | `TRADING__MAX_QUOTE_AGE_MS` (дефолт 1000 мс) |
| 7 | Максимальна різниця часу між біржами | ✅ | `TRADING__MAX_TIMESTAMP_DIFF_MS` (дефолт 1500 мс) |
| 8 | Єдина модель даних | ✅ | `backend/app/models/quote.py` (`NormalizedQuote`, тільки Decimal) |
| 9 | Доступність API/WS-каналів | ⚠️ ручна дія | [exchange-api-check.md](exchange-api-check.md) — перевірити з реального акаунту/регіону |
| 10 | NTP з резервними серверами | ⚠️ ручна дія | [ntp-setup.md](ntp-setup.md) — конфіг chrony з 4 серверами |
| 11 | Перевірка дрейфу часу при старті | ✅ | `backend/app/core/time_sync.py` — викликається при старті застосунку |
| 12 | Формули розрахунку | ✅ | [formulas.md](formulas.md) + реалізація `backend/app/spread/formulas.py` з юніт-тестами |
| 13 | Terms of Service бірж | ⚠️ ручна дія | [exchange-tos.md](exchange-tos.md) — чеклист для перевірки |

Пункти з ⚠️ — операційні дії, які неможливо виконати з коду: їх треба зробити
на реальному сервері/акаунтах перед переходом до Фази 1 (див. чеклист
"Фаза 0 → Фаза 1" у PLAN.md).
