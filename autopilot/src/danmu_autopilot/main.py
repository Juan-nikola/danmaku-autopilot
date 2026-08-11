"""FastAPI entry point for the public player gateway."""

from __future__ import annotations

from typing import Any
import hashlib
import asyncio
import json
from pathlib import Path

import httpx

from .config import Settings
from .fallback import EngineRequest, ResponseData
from .gateway import GatewayService, create_app
from .logging import configure_logging
from .misaka import MisakaClient
from .store import JobStore


class HttpEngine:
    """Transparent HTTPX engine used for the internal danmu_api service."""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=False)

    async def proxy(self, request: EngineRequest) -> ResponseData:
        headers = {key.decode(errors="ignore"): value.decode(errors="ignore") for key, value in request.headers}
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
            headers.setdefault("X-API-Key", self.token)
        url = f"{self.base_url}/{request.path.lstrip('/')}"
        if request.query:
            url = f"{url}?{request.query}"
        response = await self.client.request(request.method, url, content=request.body, headers=headers)
        body = await response.aread()
        return ResponseData(
            response.status_code,
            tuple((str(key).encode(), str(value).encode()) for key, value in response.headers.items()),
            body,
            engine="danmu_api",
        )

    async def aclose(self) -> None:
        await self.client.aclose()


def _dev_settings() -> Settings:
    """Build a local-only fallback for import-time health tooling.

    Compose rejects missing secrets before this process starts, so this branch is
    only for `python -c 'import danmu_autopilot.main'` in a source checkout.
    """

    import os

    os.environ.setdefault("MISAKA_CONTROL_KEY", "development-misaka-key")
    os.environ.setdefault("DANMU_API_TOKEN", "development-danmu-key")
    return Settings()


def build_service(settings: Settings | None = None) -> GatewayService:
    active = settings or _dev_settings()
    misaka = MisakaClient(active)
    backup = HttpEngine(str(active.danmu_api_base_url), active.danmu_api_token.get_secret_value())
    store = JobStore(Path(active.state_dir) / "autopilot.db")
    initialized = False
    init_lock = asyncio.Lock()

    async def enqueue_match(request: EngineRequest, response: ResponseData) -> None:
        nonlocal initialized
        if not initialized:
            async with init_lock:
                if not initialized:
                    await store.initialize()
                    initialized = True
        key = hashlib.sha256(request.method.encode() + b"\0" + request.path.encode() + b"\0" + request.body).hexdigest()
        payload: dict[str, Any] = {}
        try:
            decoded = json.loads(request.body or b"{}")
            if isinstance(decoded, dict):
                payload = {str(k): v for k, v in decoded.items() if isinstance(v, (str, int, float, bool))}
        except (ValueError, TypeError):
            pass
        payload.update({"method": request.method, "path": request.path, "body_sha256": hashlib.sha256(response.body).hexdigest()})
        await store.enqueue(key, payload)

    return GatewayService(misaka, backup, public_token=active.public_api_token.get_secret_value(), enqueue_match=enqueue_match)


configure_logging()
app = create_app(build_service())


__all__ = ["app", "build_service"]
