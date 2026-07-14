"""ConnectionManager: повільний клієнт не блокує broadcast (drop-oldest)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.websocket.manager import ConnectionManager


@pytest.fixture
def fake_ws():
    ws = MagicMock()
    ws.accept = AsyncMock()
    return ws


async def test_connect_and_broadcast(fake_ws):
    manager = ConnectionManager(client_queue_size=10)
    queue = await manager.connect(fake_ws)
    manager.broadcast({"type": "heartbeat", "sequence": 1})
    payload = json.loads(queue.get_nowait())
    assert payload["sequence"] == 1


async def test_slow_client_drops_oldest(fake_ws):
    manager = ConnectionManager(client_queue_size=2)
    queue = await manager.connect(fake_ws)
    for seq in range(1, 5):  # 4 повідомлення в чергу на 2
        manager.broadcast({"sequence": seq})
    assert queue.qsize() == 2
    remaining = [json.loads(queue.get_nowait())["sequence"] for _ in range(2)]
    assert remaining == [3, 4]  # найстаріші викинуті


async def test_disconnect_removes_client(fake_ws):
    manager = ConnectionManager(client_queue_size=2)
    await manager.connect(fake_ws)
    assert manager.client_count == 1
    manager.disconnect(fake_ws)
    assert manager.client_count == 0
    manager.disconnect(fake_ws)  # повторний виклик безпечний


async def test_broadcast_without_clients_is_noop():
    manager = ConnectionManager(client_queue_size=2)
    manager.broadcast({"sequence": 1})  # не кидає


async def test_two_clients_get_same_message(fake_ws):
    manager = ConnectionManager(client_queue_size=5)
    ws2 = MagicMock()
    ws2.accept = AsyncMock()
    q1 = await manager.connect(fake_ws)
    q2 = await manager.connect(ws2)
    manager.broadcast({"sequence": 7})
    assert json.loads(q1.get_nowait()) == json.loads(q2.get_nowait())
    await asyncio.sleep(0)  # тримаємо event loop чистим
