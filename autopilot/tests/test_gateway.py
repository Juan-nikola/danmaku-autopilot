import pytest

from danmu_autopilot.fallback import ResponseData
from danmu_autopilot.gateway import GatewayService


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
