from __future__ import annotations

import json

import pytest

from danmu_autopilot.fallback import EngineRequest
from danmu_autopilot.main import HttpEngine


class _Response:
    status_code = 200
    headers = {
        "content-type": "application/json",
        "content-encoding": "gzip",
        "content-length": "42",
    }

    async def aread(self) -> bytes:
        return b'{"isMatched":true}'


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []

    async def request(self, method: str, url: str, *, content: bytes, headers: dict[str, str]) -> _Response:
        self.calls.append((method, url, headers, content))
        return _Response()


@pytest.mark.asyncio
async def test_backup_engine_replaces_public_auth_and_strips_public_query_token() -> None:
    engine = HttpEngine("http://danmu-api:9321", "backup-secret")
    client = _Client()
    await engine.client.aclose()
    engine.client = client  # type: ignore[assignment]

    result = await engine.proxy(
        EngineRequest(
            "POST",
            "/api/v2/match",
            json.dumps({"fileName": "Show.S01E01.mkv"}).encode(),
            ((b"authorization", b"Bearer public-secret"), (b"x-player", b"keep")),
            "token=public-secret&client=forward",
        )
    )

    assert result.status_code == 200
    method, url, headers, _body = client.calls[0]
    assert method == "POST"
    assert url == "http://danmu-api:9321/backup-secret/api/v2/match?client=forward"
    assert headers["Authorization"] == "Bearer backup-secret"
    assert headers["X-API-Key"] == "backup-secret"
    assert headers["x-player"] == "keep"
    assert "content-encoding" not in {key.decode().lower() for key, _ in result.headers}
    assert "content-length" not in {key.decode().lower() for key, _ in result.headers}
