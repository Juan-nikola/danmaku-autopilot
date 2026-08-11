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
