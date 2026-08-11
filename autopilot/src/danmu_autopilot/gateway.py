"""Public, transparent player gateway for the two danmaku engines."""

import asyncio
import hmac
import inspect
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

from .fallback import Engine, EngineRequest, EngineRouter, ResponseData


def _safe_headers(headers: Any) -> tuple[tuple[bytes, bytes], ...]:
    blocked = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization", b"te", b"trailer", b"transfer-encoding", b"upgrade", b"content-length"}
    if isinstance(headers, dict):
        headers = headers.items()
    return tuple((str(key).lower().encode() if not isinstance(key, bytes) else key.lower(), str(value).encode() if not isinstance(value, bytes) else value) for key, value in headers if (str(key).lower().encode() if not isinstance(key, bytes) else key.lower()) not in blocked)


class GatewayService:
    def __init__(self, misaka: Engine, danmu_api: Engine, *, enqueue_match: Callable[..., Any] | None = None, public_token: str | None = None) -> None:
        self.router = EngineRouter(misaka, danmu_api)
        self.enqueue_match = enqueue_match
        self.public_token = public_token
        self._inflight_searches: dict[tuple[str, str, str], asyncio.Task[ResponseData]] = {}

    def authorized(self, headers: Any = (), query: str = "", path: str = "") -> bool:
        if not self.public_token:
            return True
        values: dict[str, str] = {}
        items = headers.items() if isinstance(headers, dict) else headers
        for key, value in items:
            values[str(key).lower()] = str(value)
        supplied = values.get("authorization", "")
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:]
        supplied = supplied or values.get("x-api-key", "")
        supplied = supplied or parse_qs(query).get("token", [""])[0]
        supplied = supplied or parse_qs(query).get("api_key", [""])[0]
        if not supplied:
            first_segment = path.strip("/").split("/", 1)[0]
            if first_segment not in {"", "api", "healthz", "readyz"}:
                supplied = first_segment
        return hmac.compare_digest(supplied, self.public_token)

    def _strip_path_token(self, path: str) -> str:
        """Accept the common ``/<token>/api/v2`` player URL form safely."""

        if not self.public_token:
            return path
        first, separator, remainder = path.lstrip("/").partition("/")
        if hmac.compare_digest(first, self.public_token):
            return "/" + remainder if separator else "/"
        return path

    async def handle(self, method: str, path: str, body: bytes = b"", headers: Any = (), query: str = "") -> ResponseData:
        forward_path = self._strip_path_token(path)
        safe_headers = _safe_headers(headers)
        # Forward may issue several identical cold searches while it is opening
        # the search screen.  Let one request populate danmu-api's cache and
        # share that result with the other callers instead of racing the source
        # fan-out and returning an early empty response.
        search_key = (method.upper(), forward_path, query)
        if method.upper() == "GET" and forward_path in {"/api/v2/search/anime", "/api/v2/search/episodes"}:
            task = self._inflight_searches.get(search_key)
            if task is None:
                task = asyncio.create_task(
                    self.router.proxy(method, forward_path, body, headers=safe_headers, query=query)
                )
                self._inflight_searches[search_key] = task
                try:
                    result = await asyncio.shield(task)
                finally:
                    if self._inflight_searches.get(search_key) is task:
                        self._inflight_searches.pop(search_key, None)
            else:
                result = await asyncio.shield(task)
        else:
            result = await self.router.proxy(method, forward_path, body, headers=safe_headers, query=query)
        if self.enqueue_match is not None and method.upper() in {"POST", "PUT"} and "/match" in path:
            try:
                scheduled = self.enqueue_match(EngineRequest(method, forward_path, body, _safe_headers(headers), query), result)
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
        if not service.authorized(request.headers.items(), request.url.query, "/" + path):
            return Response(content=b'{"detail":"unauthorized"}', status_code=401, media_type="application/json")
        data = await request.body()
        result = await service.handle(request.method, "/" + path, data, request.headers.items(), request.url.query)
        return Response(content=result.body, status_code=result.status_code, headers={key.decode(): value.decode(errors="replace") for key, value in _safe_headers(result.headers)})

    return app
