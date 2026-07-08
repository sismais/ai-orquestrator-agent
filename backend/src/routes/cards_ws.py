import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..services.card_ws import card_ws_manager

router = APIRouter(prefix="/api/cards", tags=["cards-ws"])

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint para notificações de cards"""
    await card_ws_manager.connect(websocket)
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
        card_ws_manager.disconnect(websocket)
