"""Connection manager для frontend-клієнтів (Фаза 1, п.9).

Кожен клієнт має обмежену чергу: повільний клієнт втрачає найстаріші
повідомлення (drop-oldest), але ніколи не блокує broadcast та інших
клієнтів.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, client_queue_size: int) -> None:
        self._queue_size = client_queue_size
        self._clients: dict[WebSocket, asyncio.Queue[str]] = {}

    async def connect(self, websocket: WebSocket) -> asyncio.Queue[str]:
        await websocket.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        self._clients[websocket] = queue
        logger.info("WS client connected (%d total)", len(self._clients))
        return queue

    def disconnect(self, websocket: WebSocket) -> None:
        if self._clients.pop(websocket, None) is not None:
            logger.info("WS client disconnected (%d total)", len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def broadcast(self, message: dict[str, Any]) -> None:
        if not self._clients:
            return
        payload = json.dumps(message)
        for queue in self._clients.values():
            while True:
                try:
                    queue.put_nowait(payload)
                    break
                except asyncio.QueueFull:
                    # Повільний клієнт: викидаємо найстаріше повідомлення.
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:  # pragma: no cover - гонка малоймовірна
                        break
