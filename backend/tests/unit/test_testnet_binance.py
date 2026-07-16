"""Testnet-клієнт (Фаза 4, п.6): retry policy, ідемпотентність, 4xx/5xx
поведінка — усе через httpx.MockTransport, без реальних мережевих викликів."""

from decimal import Decimal

import httpx
import pytest

from app.testnet.binance import (
    BinanceTestnetClient,
    TestnetRejectedError,
    TestnetRetryableError,
)


def _order_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "BTCUSDT",
        "orderId": 28,
        "clientOrderId": "abc123",
        "price": "0.00000000",
        "origQty": "1.00000000",
        "executedQty": "1.00000000",
        "cummulativeQuoteQty": "100.00000000",
        "status": "FILLED",
        "type": "MARKET",
        "side": "BUY",
    }
    payload.update(overrides)
    return payload


def _client(handler) -> BinanceTestnetClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://testnet.binance.vision")
    return BinanceTestnetClient(
        api_key="key",
        api_secret="secret",
        http_client=http_client,
        max_retries=2,
        backoff_base_s=0.001,
    )


class TestCreateOrder:
    async def test_successful_create_order(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-MBX-APIKEY"] == "key"
            assert "signature=" in str(request.url)
            return httpx.Response(200, json=_order_payload())

        client = _client(handler)
        result = await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="abc123")
        assert result.status == "FILLED"
        assert result.exchange_order_id == "28"
        assert result.filled_quantity == Decimal("1.00000000")
        assert result.avg_price == Decimal("100")
        await client.aclose()

    async def test_idempotent_repeat_returns_cached_result_without_http_call(self):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=_order_payload())

        client = _client(handler)
        first = await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="dup-1")
        second = await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="dup-1")
        assert calls == 1
        assert first == second
        await client.aclose()

    async def test_partial_fill_status(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_order_payload(
                    status="PARTIALLY_FILLED",
                    executedQty="0.40000000",
                    cummulativeQuoteQty="40.00000000",
                ),
            )

        client = _client(handler)
        result = await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="p1")
        assert result.status == "PARTIALLY_FILLED"
        assert result.filled_quantity == Decimal("0.40000000")
        await client.aclose()

    async def test_zero_fill_avg_price_is_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_order_payload(status="NEW", executedQty="0", cummulativeQuoteQty="0"),
            )

        client = _client(handler)
        result = await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="z1")
        assert result.avg_price is None
        await client.aclose()


class TestRetryPolicy:
    async def test_5xx_retries_then_succeeds(self):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, text="server busy")
            return httpx.Response(200, json=_order_payload())

        client = _client(handler)
        result = await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="r1")
        assert attempts == 3
        assert result.status == "FILLED"
        await client.aclose()

    async def test_5xx_retries_exhausted_raises(self):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(500, text="internal error")

        client = _client(handler)
        with pytest.raises(TestnetRetryableError):
            await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="r2")
        assert attempts == 3  # initial + max_retries(2)
        await client.aclose()

    async def test_network_error_retries_then_succeeds(self):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise httpx.ConnectError("connection refused")
            return httpx.Response(200, json=_order_payload())

        client = _client(handler)
        result = await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="n1")
        assert attempts == 2
        assert result.status == "FILLED"
        await client.aclose()

    async def test_4xx_fails_immediately_without_retry(self):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(400, text="insufficient balance")

        client = _client(handler)
        with pytest.raises(TestnetRejectedError):
            await client.create_order("BTCUSDT", "BUY", Decimal("1"), client_order_id="b1")
        assert attempts == 1
        await client.aclose()


class TestOrderStatusAndCancel:
    async def test_get_order_status(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert "origClientOrderId=abc123" in str(request.url)
            return httpx.Response(200, json=_order_payload())

        client = _client(handler)
        result = await client.get_order_status("BTCUSDT", client_order_id="abc123")
        assert result.status == "FILLED"
        await client.aclose()

    async def test_get_order_status_requires_an_identifier(self):
        client = _client(lambda request: httpx.Response(200, json=_order_payload()))
        with pytest.raises(ValueError):
            await client.get_order_status("BTCUSDT")
        await client.aclose()

    async def test_cancel_order(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            return httpx.Response(200, json=_order_payload(status="CANCELED"))

        client = _client(handler)
        result = await client.cancel_order("BTCUSDT", client_order_id="abc123")
        assert result.status == "CANCELED"
        await client.aclose()
