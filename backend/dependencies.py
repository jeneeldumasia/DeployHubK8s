import asyncio
import time as _time
from fastapi import WebSocket
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings
from worker import DeploymentWorker

# Rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# WebSocket connection manager
class _WSManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, project_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(project_id, []).append(ws)

    def disconnect(self, project_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(project_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, project_id: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(project_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(project_id, ws)

ws_manager = _WSManager()

# TTL cache for expensive system/metrics endpoints
class _TTLCache:
    def __init__(self, ttl: float = 5.0) -> None:
        self._ttl = ttl
        self._cache: dict = {}
        self._lock = asyncio.Lock()

    async def get_or_set(self, key: str, coro_factory):
        async with self._lock:
            entry = self._cache.get(key)
            if entry and (_time.monotonic() - entry["ts"]) < self._ttl:
                return entry["value"]
        value = await coro_factory()
        async with self._lock:
            self._cache[key] = {"value": value, "ts": _time.monotonic()}
        return value

_cache = _TTLCache(ttl=5.0)

# Worker instance
worker = DeploymentWorker(
    public_base_url=settings.public_base_url,
    generated_dockerfile_root=settings.generated_dockerfile_root,
    deployment_mode=settings.deployment_mode,
)
