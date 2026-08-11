"""Small, typed adapter for Misaka's external-control and player APIs.

The adapter deliberately keeps the upstream response body as bytes.  Forward and
SenPlayer consume several slightly different danmaku payloads, so decoding and
rewriting the body here would make fail-over surprisingly destructive.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fallback import EngineRequest, ResponseData

try:  # httpx is an application dependency, but importing the module stays cheap in tests.
    import httpx
except ImportError:  # pragma: no cover - exercised only in a dependency-less import check
    httpx = None  # type: ignore[assignment]


class MisakaError(RuntimeError):
    """Base class for errors raised by the typed control client."""


class MisakaUnavailable(MisakaError):
    """Transport timeout, DNS failure, or an unavailable upstream."""


class MisakaRejected(MisakaError):
    """Misaka rejected a valid request (4xx/5xx)."""


class MisakaContractChanged(MisakaError):
    """The response no longer matches the small contract this adapter needs."""


class AsyncHttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class XmlImport:
    episode_id: int | None
    xml: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    success: bool
    episode_id: int | None = None
    task_id: int | str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    items: tuple[dict[str, Any], ...]
    raw: Any


def _secret_value(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    if getter:
        return str(getter())
    return str(value)


class MisakaClient:
    """Typed, bounded HTTP adapter.

    ``settings`` may be a Pydantic Settings instance or a plain object.  Passing
    ``base_url`` and ``control_key`` directly is convenient for unit tests and
    keeps this module independent of the configuration implementation.
    """

    CONTROL_PATHS = ("/api/control/",)
    MAX_RESPONSE_BYTES = 16 * 1024 * 1024

    def __init__(
        self,
        settings: Any | None = None,
        *,
        base_url: str | None = None,
        control_key: str | None = None,
        http_client: AsyncHttpClient | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.base_url = str(base_url or getattr(settings, "misaka_base_url", "http://misaka:7768")).rstrip("/")
        self.control_key = _secret_value(control_key if control_key is not None else getattr(settings, "misaka_control_key", ""))
        self.timeout_seconds = timeout_seconds
        self._client = http_client
        self._owns_client = http_client is None

    async def __aenter__(self) -> "MisakaClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def redacted_url(url: str) -> str:
        """Redact credentials from a URL before it can reach a log handler."""

        parts = urlsplit(url)
        query = [(key, "***" if key.lower() in {"api_key", "apikey", "token", "key"} else value) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def _url(self, path: str, *, control: bool = False) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if control and self.control_key:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode({'api_key': self.control_key})}"
        return url

    async def _http(self) -> AsyncHttpClient:
        if self._client is None:
            if httpx is None:  # pragma: no cover
                raise MisakaUnavailable("httpx is not installed")
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds)),
                follow_redirects=False,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        control: bool = False,
        headers: Any = (),
        body: bytes | None = None,
        json_body: Any | None = None,
        retries: int = 0,
    ) -> ResponseData:
        url = self._url(path, control=control)
        kwargs: dict[str, Any] = {"headers": {"accept": "application/json, application/xml"}}
        hop_by_hop = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length"}
        source_headers = headers.items() if isinstance(headers, dict) else headers
        for key, value in source_headers or ():
            key_text = key.decode(errors="ignore") if isinstance(key, bytes) else str(key)
            if key_text.lower() not in hop_by_hop:
                kwargs["headers"][key_text] = value.decode(errors="ignore") if isinstance(value, bytes) else str(value)
        if body is not None:
            kwargs["content"] = body
            kwargs["headers"]["content-type"] = "application/xml; charset=utf-8"
        if json_body is not None:
            kwargs["json"] = json_body
            kwargs["headers"]["content-type"] = "application/json"
        last: BaseException | None = None
        for attempt in range(retries + 1):
            try:
                response = await (await self._http()).request(method, url, **kwargs)
                data = await self._read_response(response)
                if int(response.status_code) >= 500:
                    raise MisakaUnavailable(f"Misaka returned {response.status_code}")
                if int(response.status_code) >= 400:
                    raise MisakaRejected(f"Misaka returned {response.status_code}")
                headers = tuple((str(k).encode(), str(v).encode()) for k, v in getattr(response, "headers", {}).items())
                return ResponseData(int(response.status_code), headers, data, engine="misaka")
            except (MisakaRejected, MisakaContractChanged):
                raise
            except Exception as exc:  # transport failures are safe to retry for reads only
                last = exc
                if attempt < retries:
                    await asyncio.sleep(0.05 * (attempt + 1))
        raise MisakaUnavailable("Misaka request failed") from last

    async def _read_response(self, response: Any) -> bytes:
        if hasattr(response, "aread"):
            body = await response.aread()
        else:
            body = bytes(getattr(response, "content", b""))
        if len(body) > self.MAX_RESPONSE_BYTES:
            raise MisakaContractChanged("Misaka response exceeds configured limit")
        return body

    async def proxy(self, request: EngineRequest) -> ResponseData:
        """Proxy an arbitrary player request while preserving status, headers and bytes."""

        path = request.path or "/"
        control = path.startswith("/api/control/")
        return await self._request(
            request.method.upper(),
            path + (("?" + request.query) if request.query else ""),
            control=control,
            headers=request.headers,
            body=request.body,
            retries=2 if request.method.upper() in {"GET", "HEAD", "OPTIONS"} else 0,
        )

    async def search(self, query: str) -> SearchResult:
        response = await self._request("POST", "/api/control/search", control=True, json_body={"keyword": query}, retries=2)
        try:
            payload = json.loads(response.body or b"{}")
        except (ValueError, TypeError) as exc:
            raise MisakaContractChanged("Misaka search returned non-JSON") from exc
        if isinstance(payload, list):
            items = tuple(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            values = payload.get("data", payload.get("results", payload.get("items", [])))
            items = tuple(item for item in values if isinstance(item, dict)) if isinstance(values, list) else ()
        else:
            raise MisakaContractChanged("Misaka search response has an unknown shape")
        return SearchResult(items, payload)

    async def auto_import(self, request: dict[str, Any]) -> ImportResult:
        return await self._import_result("/api/control/import/auto", request)

    async def import_xml(self, request: XmlImport) -> ImportResult:
        payload: dict[str, Any] = {"xml": request.xml}
        if request.episode_id is not None:
            payload["episodeId"] = request.episode_id
        response = await self._request("POST", "/api/control/import/xml", control=True, json_body=payload)
        return self._parse_import(response, request.episode_id)

    async def _import_result(self, path: str, request: dict[str, Any]) -> ImportResult:
        response = await self._request("POST", path, control=True, json_body=request)
        return self._parse_import(response, request.get("episodeId") or request.get("episode_id"))

    @staticmethod
    def _parse_import(response: ResponseData, fallback_episode: Any = None) -> ImportResult:
        try:
            payload = json.loads(response.body or b"{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            raise MisakaContractChanged("Misaka import response has an unknown shape")
        success = bool(payload.get("success", payload.get("ok", response.status_code < 300)))
        episode = payload.get("episodeId", payload.get("episode_id", fallback_episode))
        task = payload.get("taskId", payload.get("task_id"))
        return ImportResult(success, episode_id=episode, task_id=task, raw=payload)

    async def get_comments(self, episode_id: int) -> ResponseData:
        return await self._request("GET", f"/api/control/danmaku/{int(episode_id)}", control=True, retries=2)

    async def replace_comments(self, episode_id: int, comments: Any) -> ImportResult:
        response = await self._request("POST", f"/api/control/danmaku/{int(episode_id)}", control=True, json_body={"comments": comments})
        return self._parse_import(response, episode_id)

    async def task(self, task_id: int | str) -> dict[str, Any]:
        response = await self._request("GET", f"/api/control/tasks/{task_id}", control=True, retries=2)
        try:
            payload = json.loads(response.body or b"{}")
        except (TypeError, ValueError) as exc:
            raise MisakaContractChanged("Misaka task response is not JSON") from exc
        if not isinstance(payload, dict):
            raise MisakaContractChanged("Misaka task response has an unknown shape")
        return payload
