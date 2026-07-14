"""WS endpoint для dashboard: віддає повідомлення з персональної черги."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/spreads")
async def spreads_ws(websocket: WebSocket) -> None:
    manager = websocket.app.state.ws_manager
    queue = await manager.connect(websocket)
    try:
        while True:
            payload = await queue.get()
            await websocket.send_text(payload)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - обрив клієнта не має валити застосунок
        logger.debug("WS client error", exc_info=True)
    finally:
        manager.disconnect(websocket)
