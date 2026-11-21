"""Minimal authenticated WebSocket client for the MindPool broker."""
from __future__ import annotations
import json
from typing import Any, AsyncIterator
import httpx
import websockets

class BrokerClient:
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.websocket = None

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()

    async def connect_worker(self):
        ws_url = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        self.websocket = await websockets.connect(f"{ws_url}/ws/{self.access_token}", ping_interval=20, ping_timeout=20)
        await self.websocket.send(json.dumps({"type": "worker_ready"}))
        return self.websocket

    async def send_result(self, job_id: int, result: str):
        if not self.websocket:
            raise RuntimeError("Broker connection is not active.")
        await self.websocket.send(json.dumps({"type": "worker_result", "job_id": job_id, "result": result}))

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        if not self.websocket:
            raise RuntimeError("Connect to the broker first.")
        async for message in self.websocket:
            yield json.loads(message)

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
