"""Broadcast job progress and other events to connected UI clients over WebSocket."""

import asyncio
from typing import Any

from fastapi import WebSocket


class EventHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, event: str, data: Any = None) -> None:
        """Thread-safe publish, for worker threads and sync routes."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.publish(event, data), self._loop)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def publish(self, event: str, data: Any = None) -> None:
        message = {"event": event, "data": data}
        async with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)
