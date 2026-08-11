"""Public, transparent player gateway for the two danmaku engines."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable

from .fallback import Engine, EngineRequest, EngineRouter, ResponseData


def _safe_headers(headers: Any) -> tuple[tuple[bytes, bytes], ...]:
    blocked = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization", b"te", b"trailer", b"transfer-encoding", b"upgrade", b"content-length"}
    if isinstance(headers, dict):
        headers = headers.items()
    return tuple((str(key).lower().encode() if not isinstance(key, bytes) else key.lower(), str(value).encode() if not isinstance(value, bytes) else value) for key, value in headers if (str(key).lower().encode() if not isinstance(key, bytes) else key.lower()) not in blocked)


class GatewayService:
    def __init__(self, misaka: Engine, danmu_api: Engine, *, enqueue_match: Callable[..., Any] | None = None) -> None:
        self.router = EngineRouter(misaka, danmu_api)
        self.enqueue_match = enqueue_match

    async def handle(self, method: str, path: str, body: bytes = b"", headers: Any = (), query: str = "") -> ResponseData:
        result = await self.router.proxy(method, path, body, headers=_safe_headers(headers), query=query)
        if self.enqueue_match is not None and method.upper() in {"POST", "PUT"} and "/match" in path:
            try:
                scheduled = self.enqueue_match(EngineRequest(method, path, body, _safe_headers(headers), query), result)
                if inspect.isawaitable(scheduled):
                    asyncio.create_task(self._swallow(scheduled))
            except Exception:
                # Analysis is optional; the player response is already complete.
                pass
        if result.engine and not any(key.lower() == b"x-danmu-engine" for key, _ in result.headers):
            result = ResponseData(
                result.status_code,
                result.headers + ((b"x-danmu-engine", result.engine.encode()),),
                result.body,
                result.engine,
            )
        return result

    @staticmethod
    async def _swallow(awaitable: Awaitable[Any]) -> None:
        try:
            await awaitable
        except Exception:
            return

    def healthz(self) -> dict[str, str]:
        return {"status": "ok"}

    async def readyz(self) -> dict[str, str]:
        healthy = [self.router._healthy(name) for name in ("misaka", "danmu_api")]
        return {"status": "ok" if any(healthy) else "degraded"}


def create_app(service: GatewayService) -> Any:
    """Create the optional FastAPI surface without importing FastAPI at module load."""

    try:
        from fastapi import FastAPI, Request, Response
    except ImportError as exc:  # pragma: no cover - local development without dependencies
        raise RuntimeError("FastAPI is required to create the gateway application") from exc

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return service.healthz()

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return await service.readyz()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def proxy(path: str, request: Request) -> Response:
        data = await request.body()
        result = await service.handle(request.method, "/" + path, data, request.headers.items(), request.url.query)
        return Response(content=result.body, status_code=result.status_code, headers={key.decode(): value.decode(errors="replace") for key, value in _safe_headers(result.headers)})

    return app
