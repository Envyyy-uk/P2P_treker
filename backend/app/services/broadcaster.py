"""Broadcaster: періодичний push розрахованих спредів на frontend.

Не транслює кожен біржовий тик — пушить агрегований стан з частотою
frontend_push_rate_hz (5–10/с за планом). Кожне повідомлення має
sequence для виявлення пропусків, heartbeat йде окремим типом.
"""

import asyncio
import logging

from app.api.websocket.manager import ConnectionManager
from app.core.config import WebSocketConfig
from app.quote_cache.cache import now_ms
from app.spread.engine import SpreadEngine

logger = logging.getLogger(__name__)


class Broadcaster:
    def __init__(
        self,
        engine: SpreadEngine,
        manager: ConnectionManager,
        ws_config: WebSocketConfig,
    ) -> None:
        self._engine = engine
        self._manager = manager
        self._cfg = ws_config
        self._sequence = 0
        self._task: asyncio.Task[None] | None = None

    @property
    def sequence(self) -> int:
        return self._sequence

    def build_message(self) -> dict[str, object]:
        self._sequence += 1
        current = now_ms()
        rows = self._engine.compute_all(current)
        return {
            "type": "spread_update",
            "sequence": self._sequence,
            "generated_at": current,
            "data": [row.to_wire() for row in rows],
        }

    def build_heartbeat(self) -> dict[str, object]:
        self._sequence += 1
        return {"type": "heartbeat", "sequence": self._sequence, "generated_at": now_ms()}

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="broadcaster")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        push_interval = 1.0 / self._cfg.frontend_push_rate_hz
        since_heartbeat = 0.0
        while True:
            try:
                if self._manager.client_count:
                    self._manager.broadcast(self.build_message())
                    since_heartbeat += push_interval
                    if since_heartbeat >= self._cfg.heartbeat_interval_s:
                        self._manager.broadcast(self.build_heartbeat())
                        since_heartbeat = 0.0
            except Exception:  # noqa: BLE001 - цикл push не має вмирати
                logger.exception("Broadcast iteration failed")
            await asyncio.sleep(push_interval)
