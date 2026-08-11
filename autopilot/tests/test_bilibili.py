import json

import httpx
import pytest

from danmu_autopilot.sources.bilibili import BilibiliClient, SourceAccessDenied


@pytest.mark.asyncio
async def test_empty_view_points_are_valid():
    def handler(request):
        if request.url.path.endswith("/x/web-interface/view"):
            return httpx.Response(200, json={"code": 0, "data": {"duration": 17_283, "cid": 35_321_351_311}})
        return httpx.Response(200, json={"code": 0, "data": {"view_points": [], "preview_toast": ""}})

    client = BilibiliClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    meta = await client.resolve("BV1HS6ZBiE43")
    await client.close()
    assert meta.duration_ms == 17_283_000
    assert meta.view_points == ()


@pytest.mark.asyncio
async def test_paid_preview_without_entitlement_is_not_bypassed():
    def handler(request):
        return httpx.Response(200, json={"code": -403, "message": "购买观看", "data": {"permission": 0}})

    client = BilibiliClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(SourceAccessDenied):
        await client.fetch_comments(35_321_351_311)
    await client.close()
