import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..services.execution_ws import execution_ws_manager

router = APIRouter(tags=["execution"])


@router.websocket("/api/execution/ws/{card_id}")
async def execution_websocket(websocket: WebSocket, card_id: str):
    await execution_ws_manager.connect(card_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Heartbeat: responde pong ao ping (useWebSocketBase),
            # senao o cliente estoura o pongTimeout e reconecta em loop.
            try:
                if json.loads(data).get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except (ValueError, TypeError):
                pass
    except WebSocketDisconnect:
        execution_ws_manager.disconnect(card_id, websocket)
