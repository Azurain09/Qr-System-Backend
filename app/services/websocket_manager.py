from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.kitchen_connections: list[WebSocket] = []
        self.order_connections: dict[int, list[WebSocket]] = {}
        self.catalog_connections: list[WebSocket] = []

    async def connect_kitchen(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.kitchen_connections.append(websocket)

    def disconnect_kitchen(self, websocket: WebSocket) -> None:
        if websocket in self.kitchen_connections:
            self.kitchen_connections.remove(websocket)

    async def connect_catalog(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.catalog_connections.append(websocket)

    def disconnect_catalog(self, websocket: WebSocket) -> None:
        if websocket in self.catalog_connections:
            self.catalog_connections.remove(websocket)

    async def connect_order(self, order_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.order_connections.setdefault(order_id, []).append(websocket)

    def disconnect_order(self, order_id: int, websocket: WebSocket) -> None:
        sockets = self.order_connections.get(order_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets and order_id in self.order_connections:
            del self.order_connections[order_id]

    async def broadcast_kitchen(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for socket in self.kitchen_connections:
            try:
                await socket.send_json(payload)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect_kitchen(socket)

    async def broadcast_catalog(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for socket in self.catalog_connections:
            try:
                await socket.send_json(payload)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect_catalog(socket)

    async def broadcast_order(self, order_id: int, payload: dict) -> None:
        dead: list[WebSocket] = []
        for socket in self.order_connections.get(order_id, []):
            try:
                await socket.send_json(payload)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect_order(order_id, socket)


manager = ConnectionManager()
