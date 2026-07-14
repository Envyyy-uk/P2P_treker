# Фаза 1 — Live моніторинг: що зроблено

| Компонент плану | Реалізація |
|-----------------|------------|
| Exchange Adapters (єдиний інтерфейс) | `app/exchanges/base.py` (інтерфейс), `base_ws.py` (спільна надійність), `binance/`, `bybit/`, `okx/` |
| Надійність WS (reconnect, backoff, heartbeat, ping/pong, resubscribe, timeout detection, graceful shutdown) | `app/exchanges/base_ws.py`; Bybit ping 20с, OKX ping 25с, Binance — WS ping-фрейми |
| Нормалізація даних | `app/normalizer/{binance,bybit,okx}.py` → `NormalizedQuote`; Bybit stateful (snapshot/delta, скидання після reconnect) |
| Quote Cache | `app/quote_cache/cache.py`: `quotes[exchange][market_type][symbol]`, sequence-захист, статуси з'єднань |
| Freshness | quote_age_ms / timestamp_diff_ms / stale — рахуються в Spread Engine, stale позначається, не приховується |
| Spread Engine | `app/spread/engine.py`: обидва напрямки для кожної пари бірж (6 напрямків для 3 бірж), Decimal, taker fees, пороги обсягу, `calculation_version` |
| FastAPI WebSocket | `/ws/spreads`: push 5–10/с (конфіг), sequence, heartbeat, bounded client queue (drop-oldest для повільних клієнтів) |
| React Dashboard | `frontend/`: таблиця з усіма колонками плану, сортування за Net, фільтри (біржа/пара/min spread/min обсяг/valid), кольори, STALE/OK/SKIP-бейджі, статус Connected/Reconnecting/Offline, час останнього оновлення, пауза UI, деталі пари справа після кліку, zoom вимкнено |

## Джерела даних

| Біржа | Канал | Особливості |
|-------|-------|-------------|
| Binance | `<symbol>@bookTicker` | немає event time → `exchange_timestamp = received_timestamp` |
| Bybit | `orderbook.1.<symbol>` (v5 spot) | snapshot/delta, qty=0 видаляє рівень, delta до snapshot ігнорується |
| OKX | `bbo-tbt` | кожне повідомлення — повний top-of-book |

## Запуск

```bash
# backend (строго 1 worker)
cd backend && uv run uvicorn app.main:app --workers 1

# frontend (dev, проксює /ws на :8000)
cd frontend && npm install && npm run dev
```

## Перевірено в цьому середовищі

- 99 юніт/інтеграційних тестів; ruff, black, mypy strict — чисто.
- Живий запуск: reconnect з exponential backoff (1→2→4→8с), health-статуси,
  graceful shutdown по SIGTERM ("Shutdown complete" у лозі).
- ⚠️ Живі котирування НЕ перевірені: sandbox-проксі блокує WSS до бірж.
  Перед чеклистом "Фаза 1 → Фаза 2" запустити на сервері з відкритим
  egress і переконатись, що всі 3 адаптери отримують повідомлення
  (`/health` → `exchanges.*.last_message_at_ms`).
