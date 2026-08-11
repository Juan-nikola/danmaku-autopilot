import pytest

from danmu_autopilot.misaka import (
    MisakaClient,
    XmlImport,
)


class FakeResponse:
    status_code = 200
    headers = {
        "content-type": "application/json",
        "content-encoding": "gzip",
        "content-length": "42",
    }

    async def aread(self):
        return b'{"success":true,"episodeId":42}'


class FakeHttp:
    def __init__(self):
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse()

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_control_key_is_query_parameter_and_import_is_typed():
    http = FakeHttp()
    client = MisakaClient(
        base_url="http://misaka:7768",
        control_key="secret-control-key",
        http_client=http,
    )

    result = await client.import_xml(XmlImport(episode_id=42, xml="<i/>"))

    assert result.episode_id == 42
    assert result.success is True
    method, url, _ = http.calls[0]
    assert method == "POST"
    assert "api_key=secret-control-key" in url
    assert "secret-control-key" not in client.redacted_url(url)


@pytest.mark.asyncio
async def test_read_requests_retry_three_times_but_writes_do_not_retry():
    class UnavailableHttp(FakeHttp):
        async def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            raise OSError("connection reset")

    http = UnavailableHttp()
    client = MisakaClient(base_url="http://misaka:7768", control_key="key", http_client=http)

    with pytest.raises(Exception):
        await client.search("Show")
    assert len(http.calls) == 3

    http.calls.clear()
    with pytest.raises(Exception):
        await client.import_xml(XmlImport(episode_id=1, xml="<i/>"))
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_public_v2_player_path_maps_to_misaka_v1_and_preserves_json_content_type():
    http = FakeHttp()
    client = MisakaClient(
        base_url="http://misaka:7768",
        player_token="internal-player-token",
        http_client=http,
    )

    await client.proxy(
        type("Request", (), {
            "method": "POST",
            "path": "/api/v2/match",
            "query": "token=public-token",
            "body": b'{"fileName":"Show.S01E01.mkv"}',
            "headers": ((b"content-type", b"application/json"),),
        })()
    )

    method, url, kwargs = http.calls[0]
    assert method == "POST"
    assert "/api/v1/internal-player-token/match?token=public-token" in url
    assert kwargs["headers"]["content-type"] == "application/json"
    response_headers = {key.decode().lower() for key, _ in (await client.proxy(
        type("Request", (), {
            "method": "GET",
            "path": "/api/v2/search/anime",
            "query": "",
            "body": b"",
            "headers": (),
        })()
    )).headers}
    assert "content-encoding" not in response_headers
    assert "content-length" not in response_headers
