import pytest

from danmu_autopilot.fallback import EngineRouter, ResponseData


class FakeEngine:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def proxy(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_primary_no_match_uses_backup_engine():
    primary = FakeEngine(ResponseData(200, (), b'{"isMatched":false}'))
    backup = FakeEngine(ResponseData(200, (), b'{"isMatched":true,"animeId":8}'))
    router = EngineRouter(primary, backup)

    result = await router.proxy("POST", "/api/v2/match", b"{}", headers={})

    assert result.body == b'{"isMatched":true,"animeId":8}'
    assert result.engine == "danmu_api"
    assert len(primary.calls) == 1
    assert len(backup.calls) == 1


@pytest.mark.asyncio
async def test_unhealthy_backup_never_delays_primary():
    primary = FakeEngine(ResponseData(200, (), b'{"isMatched":true}'))
    backup = FakeEngine(error=TimeoutError())
    router = EngineRouter(primary, backup)

    result = await router.proxy("POST", "/api/v2/match", b"{}", headers={})

    assert result.engine == "misaka"
    assert result.body == b'{"isMatched":true}'


@pytest.mark.asyncio
async def test_true_match_without_top_level_anime_id_does_not_fail_over():
    primary = FakeEngine(ResponseData(200, (), b'{"isMatched":true,"matches":[{"episodeId":1}]}'))
    backup = FakeEngine(error=AssertionError("backup should not be called"))
    router = EngineRouter(primary, backup)

    result = await router.proxy("POST", "/api/v2/match", b"{}", headers={})

    assert result.engine == "misaka"
    assert backup.calls == []


@pytest.mark.asyncio
async def test_empty_comments_use_backup_engine():
    primary = FakeEngine(ResponseData(200, (), b'{"count":0,"comments":[]}'))
    backup = FakeEngine(ResponseData(200, (), b'{"count":1,"comments":[{"m":"ok"}]}'))
    router = EngineRouter(primary, backup)

    result = await router.proxy("GET", "/api/v2/comment/1", b"", headers={})

    assert result.engine == "danmu_api"
    assert result.body == b'{"count":1,"comments":[{"m":"ok"}]}'


@pytest.mark.asyncio
async def test_transport_failure_falls_back_without_changing_backup_bytes():
    primary = FakeEngine(error=OSError("down"))
    backup = FakeEngine(ResponseData(201, ((b"x-test", b"ok"),), b"<i>ok</i>"))
    router = EngineRouter(primary, backup)

    result = await router.proxy("GET", "/api/v2/comment", b"", headers={})

    assert (result.status_code, result.headers, result.body) == (201, ((b"x-test", b"ok"),), b"<i>ok</i>")
    assert result.engine == "danmu_api"
