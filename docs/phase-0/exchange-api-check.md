# Доступність API та WebSocket-каналів (Фаза 0, п.9)

Перевірити з того акаунту й регіону/сервера, звідки реально працюватиме
система (доступність відрізняється за юрисдикцією).

## Потрібні канали для MVP (Spot, read-only)

| Біржа | REST (snapshot/fees) | WS book ticker (top-of-book) | Docs |
|-------|----------------------|------------------------------|------|
| Binance | `GET /api/v3/depth`, `GET /api/v3/account/commission` | `wss://stream.binance.com:9443/ws/<symbol>@bookTicker` | https://developers.binance.com/docs/binance-spot-api-docs |
| Bybit | `GET /v5/market/orderbook`, `GET /v5/account/fee-rate` | `wss://stream.bybit.com/v5/public/spot`, topic `orderbook.1.<symbol>` | https://bybit-exchange.github.io/docs/v5/intro |
| OKX | `GET /api/v5/market/books`, `GET /api/v5/account/trade-fee` | `wss://ws.okx.com:8443/ws/v5/public`, channel `bbo-tbt` / `books5` | https://www.okx.com/docs-v5/en/ |

## Чеклист ручної перевірки

- [ ] Публічні WS-канали доступні з production-сервера (без VPN-обходів).
- [ ] REST endpoints комісій доступні з read-only ключем.
- [ ] Rate limits достатні для 5 пар × 3 біржі.
- [ ] Зафіксовано ліміт одночасних WS-підключень і підписок на з'єднання.
- [ ] Перевірено, чи потрібен ping/pong з боку клієнта (Bybit/OKX — так).

Швидка перевірка публічних endpoint'ів (без ключів):

```bash
curl -s 'https://api.binance.com/api/v3/ticker/bookTicker?symbol=BTCUSDT'
curl -s 'https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT'
curl -s 'https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT'
```
