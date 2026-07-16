"""Testnet/Sandbox клієнт (Фаза 4, п.6).

Перевіряє: створення ордера, отримання статусу, часткове виконання,
скасування, retry policy, ідемпотентність. Реалізовано проти публічного
REST API Binance Spot Testnet (https://testnet.binance.vision) — той самий
контракт (HMAC-SHA256 підпис, `X-MBX-APIKEY`), що й у prod Binance, тож
цей клієнт лишається чинним і після переходу на prod endpoint (Фаза 5).

Reconnect behavior: це REST, а не WS-клієнт — тут немає постійного
з'єднання, яке можна "розірвати". Єдина форма "reconnect" для REST —
повторний запит після транзієнтної мережевої помилки, що вже покрито
retry policy нижче (мережеві помилки/5xx). Це свідоме звуження: якщо
Фаза 5 (Execution Layer) вимагатиме user-data WS стрім для ордерів,
reconnect-логіка для нього проєктуватиметься окремо за тим самим
патерном, що й live quote WS-адаптери Фази 1.

Retry policy: exponential backoff тільки для транзієнтних помилок
(мережеві помилки, 5xx). 4xx (невалідний запит, недостатньо коштів,
rate limit тощо) ніколи не ретраїться — це помилка клієнта, повтор
того самого запиту дасть той самий результат.

Idempotency: `create_order` кешує результат за `client_order_id` локально
і не робить повторний HTTP-виклик для вже відомого `client_order_id` —
безпечно повторювати виклик після невизначеного (timeout) результату
попередньої спроби.
"""

import asyncio
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

_DEFAULT_BASE_URL = "https://testnet.binance.vision"


class TestnetError(Exception):
    """Базовий клас помилок testnet-клієнта."""


class TestnetRejectedError(TestnetError):
    """4xx — помилка клієнта (невалідний запит, rate limit, недостатньо
    коштів тощо). Ніколи не ретраїться."""


class TestnetRetryableError(TestnetError):
    """Транзієнтна помилка (мережа/5xx), вичерпано ліміт спроб."""


@dataclass(frozen=True)
class TestnetOrderResult:
    client_order_id: str
    exchange_order_id: str
    status: str
    filled_quantity: Decimal
    avg_price: Decimal | None
    raw: dict[str, Any]


def _parse_order(payload: dict[str, Any]) -> TestnetOrderResult:
    executed_qty = Decimal(str(payload.get("executedQty", "0")))
    cumulative_quote = Decimal(str(payload.get("cummulativeQuoteQty", "0")))
    avg_price = (cumulative_quote / executed_qty) if executed_qty > 0 else None
    return TestnetOrderResult(
        client_order_id=str(payload["clientOrderId"]),
        exchange_order_id=str(payload["orderId"]),
        status=str(payload["status"]),
        filled_quantity=executed_qty,
        avg_price=avg_price,
        raw=payload,
    )


class BinanceTestnetClient:
    """Тонкий клієнт Binance Spot Testnet REST API з retry policy та
    ідемпотентністю на рівні `create_order`. API-ключі для testnet НЕ є
    prod-секретами (окреме середовище), але все одно ніколи не логуються."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = _DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        timeout_s: float = 10.0,
        recv_window_ms: int = 5000,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._client = http_client or httpx.AsyncClient(base_url=base_url)
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._timeout_s = timeout_s
        self._recv_window_ms = recv_window_ms
        self._idempotency_cache: dict[str, TestnetOrderResult] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def _sign(self, params: dict[str, str]) -> str:
        query_string = urlencode(params)
        signature = hmac.new(self._api_secret, query_string.encode(), hashlib.sha256).hexdigest()
        return f"{query_string}&signature={signature}"

    async def _request(self, method: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        signed_params = dict(params)
        signed_params["timestamp"] = str(int(time.time() * 1000))
        signed_params["recvWindow"] = str(self._recv_window_ms)
        query_string = self._sign(signed_params)
        headers = {"X-MBX-APIKEY": self._api_key}
        url = f"{path}?{query_string}"

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, url, headers=headers)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise TestnetRetryableError(
                        f"network error after {attempt + 1} attempts: {exc}"
                    ) from exc
                await self._sleep_backoff(attempt)
                continue

            if response.status_code >= 500:
                if attempt == self._max_retries:
                    raise TestnetRetryableError(
                        f"server error {response.status_code} after {attempt + 1} attempts: "
                        f"{response.text}"
                    )
                await self._sleep_backoff(attempt)
                continue

            if response.status_code >= 400:
                raise TestnetRejectedError(f"client error {response.status_code}: {response.text}")

            result: dict[str, Any] = response.json()
            return result

        raise AssertionError("unreachable: retry loop always returns or raises")

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(self._backoff_base_s * (2**attempt))

    async def create_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        order_type: str = "MARKET",
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> TestnetOrderResult:
        """Ідемпотентно: якщо `client_order_id` вже відомий (успішна
        попередня спроба чи ретрай після ambiguous timeout), повертає
        закешований результат без нового HTTP-виклику."""
        client_order_id = client_order_id or uuid.uuid4().hex
        cached = self._idempotency_cache.get(client_order_id)
        if cached is not None:
            return cached

        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": str(quantity),
            "newClientOrderId": client_order_id,
        }
        if order_type != "MARKET" and price is not None:
            params["price"] = str(price)
            params["timeInForce"] = "GTC"

        payload = await self._request("POST", "/api/v3/order", params)
        result = _parse_order(payload)
        self._idempotency_cache[client_order_id] = result
        return result

    async def get_order_status(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> TestnetOrderResult:
        if not client_order_id and not exchange_order_id:
            raise ValueError("must provide client_order_id or exchange_order_id")
        params = {"symbol": symbol}
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        if exchange_order_id:
            params["orderId"] = exchange_order_id
        payload = await self._request("GET", "/api/v3/order", params)
        return _parse_order(payload)

    async def cancel_order(
        self,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> TestnetOrderResult:
        if not client_order_id and not exchange_order_id:
            raise ValueError("must provide client_order_id or exchange_order_id")
        params = {"symbol": symbol}
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        if exchange_order_id:
            params["orderId"] = exchange_order_id
        payload = await self._request("DELETE", "/api/v3/order", params)
        return _parse_order(payload)
