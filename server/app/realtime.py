"""In-process WebSocket registry for low-latency development commands."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class DeviceConnections:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            old = self._connections.get(device_id)
            self._connections[device_id] = websocket
        if old is not None and old is not websocket:
            try:
                await old.close(code=4000, reason="replaced by a newer connection")
            except RuntimeError:
                pass

    async def disconnect(self, device_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if self._connections.get(device_id) is websocket:
                self._connections.pop(device_id, None)

    async def send(self, device_id: str, message: dict[str, Any]) -> bool:
        async with self._lock:
            websocket = self._connections.get(device_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(message)
            return True
        except (RuntimeError, OSError):
            await self.disconnect(device_id, websocket)
            return False


class ParentEvents:
    """In-process, thread-safe change signals for signed-in dashboard tabs."""

    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue[str]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def subscribe(self, parent_id: str) -> asyncio.Queue[str]:
        self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=20)
        self._subscribers.setdefault(parent_id, set()).add(queue)
        return queue

    def unsubscribe(self, parent_id: str, queue: asyncio.Queue[str]) -> None:
        subscribers = self._subscribers.get(parent_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(parent_id, None)

    def notify(self, parent_id: str, kind: str = "status") -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._publish, parent_id, kind)

    def _publish(self, parent_id: str, kind: str) -> None:
        for queue in tuple(self._subscribers.get(parent_id, ())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(kind)
