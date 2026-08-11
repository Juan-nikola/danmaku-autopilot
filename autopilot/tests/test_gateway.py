import asyncio

import pytest
import httpx

from danmu_autopilot.fallback import ResponseData
from danmu_autopilot.gateway import GatewayService, create_app


class Engine:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def proxy(self, request):
        self.calls.append(request)
        return self.response


class DelayedEngine(Engine):
    def __init__(self, response, delay=0.01):
        super().__init__(response)
        self.delay = delay

    async def proxy(self, request):
        self.calls.append(request)
        await asyncio.sleep(self.delay)
        return self.response


@pytest.mark.asyncio
async def test_gateway_service_preserves_bytes_and_exposes_engine_header():
    misaka = Engine(ResponseData(200, ((b"content-type", b"application/json"),), b'{"isMatched":true}'))
    backup = Engine(ResponseData(200, (), b'{"isMatched":false}'))
    service = GatewayService(misaka, backup)

    result = await service.handle("POST", "/device/api/v2/match", b'{"fileName":"Show.S01E01.mkv"}', {})

    assert result.status_code == 200
    assert result.body == b'{"isMatched":true}'
    assert (b"x-danmu-engine", b"misaka") in result.headers


@pytest.mark.asyncio
async def test_gateway_analysis_failure_does_not_change_response():
    misaka = Engine(ResponseData(200, (), b'{"isMatched":true}'))
    backup = Engine(ResponseData(200, (), b'{"isMatched":false}'))
    service = GatewayService(misaka, backup, enqueue_match=lambda *_: (_ for _ in ()).throw(RuntimeError("queue down")))

    result = await service.handle("POST", "/api/v2/match", b"{}", {})

    assert result.status_code == 200
    assert result.body == b'{"isMatched":true}'


@pytest.mark.asyncio
async def test_path_token_is_removed_before_forwarding_to_engines():
    misaka = Engine(ResponseData(200, (), b'{"isMatched":true,"matches":[{"episodeId":1}]}'))
    backup = Engine(ResponseData(200, (), b'{"isMatched":false}'))
    service = GatewayService(misaka, backup, public_token="long-private-token")

    await service.handle("GET", "/long-private-token/api/v2/search/anime", b"", {})

    assert misaka.calls[0].path == "/api/v2/search/anime"


@pytest.mark.asyncio
async def test_concurrent_identical_searches_share_one_cold_request():
    misaka = DelayedEngine(ResponseData(200, (), b'{"animes":[]}'))
    backup = DelayedEngine(ResponseData(200, (), b'{"success":true,"animes":[{"animeId":1}]}'))
    service = GatewayService(misaka, backup)

    results = await asyncio.gather(
        service.handle("GET", "/api/v2/search/anime", query="keyword=Show"),
        service.handle("GET", "/api/v2/search/anime", query="keyword=Show"),
    )

    assert [result.body for result in results] == [backup.response.body, backup.response.body]
    assert len(misaka.calls) == 1
    assert len(backup.calls) == 1


def test_health_payload_does_not_include_secrets_or_urls():
    service = GatewayService(Engine(ResponseData(200, (), b"{}")), Engine(ResponseData(200, (), b"{}")))
    assert service.healthz() == {"status": "ok"}


def test_public_token_is_checked_at_gateway_boundary():
    service = GatewayService(
        Engine(ResponseData(200, (), b"{}")),
        Engine(ResponseData(200, (), b"{}")),
        public_token="long-private-token",
    )
    assert not service.authorized((), "")
    assert service.authorized((("authorization", "Bearer long-private-token"),), "")
    assert service.authorized((), "token=long-private-token")


@pytest.mark.asyncio
async def test_fastapi_surface_passes_request_to_gateway_and_enforces_token():
    service = GatewayService(
        Engine(ResponseData(200, ((b"content-type", b"application/json"),), b"{}")),
        Engine(ResponseData(200, (), b"{}")),
        public_token="long-private-token",
    )
    app = create_app(service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/healthz")
        invalid = await client.get("/api/v2/match?token=invalid")
        valid = await client.get("/api/v2/match?token=long-private-token")

    assert health.status_code == 200
    assert invalid.status_code == 401
    assert valid.status_code == 200
