from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


class ConnectionManager:
    def __init__(self) -> None:
        self.active: dict[str, set[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        connections = self.active.get(user_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self.active.pop(user_id, None)

    async def broadcast_to_users(self, user_ids: list[str], payload: dict) -> None:
        for user_id in user_ids:
            for websocket in list(self.active.get(user_id, ())):
                try:
                    await websocket.send_json(payload)
                except (WebSocketDisconnect, RuntimeError, OSError):
                    self.disconnect(user_id, websocket)


manager = ConnectionManager()
