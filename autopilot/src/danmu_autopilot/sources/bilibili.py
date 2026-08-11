"""Minimal, authorized Bilibili metadata and danmaku adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class SourceAccessDenied(RuntimeError):
    """The account is not entitled to access a source; do not bypass it."""


@dataclass(frozen=True, slots=True)
class BilibiliSourceMeta:
    bvid: str
    cid: int
    duration_ms: int
    view_points: tuple[int, ...] = ()
    preview_toast: str = ""


class BilibiliClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None, cookie: str | None = None) -> None:
        self._client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        self._owns_client = http_client is None
        self._cookie = cookie

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_json(self, path: str, **params: object) -> dict[str, Any]:
        headers = {"User-Agent": "Mozilla/5.0 (danmu-autopilot; authorized client)"}
        if self._cookie:
            headers["Cookie"] = self._cookie
        response = await self._client.get(f"https://api.bilibili.com{path}", params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("unexpected Bilibili response")
        return payload

    async def resolve(self, url_or_bvid: str) -> BilibiliSourceMeta:
        bvid = url_or_bvid.rstrip("/").split("/")[-1]
        if "?" in bvid:
            bvid = bvid.split("?", 1)[0]
        view = await self._get_json("/x/web-interface/view", bvid=bvid)
        if int(view.get("code", 0)) != 0:
            raise SourceAccessDenied(str(view.get("message", "Bilibili metadata unavailable")))
        data = view.get("data") or {}
        cid = int(data.get("cid", 0))
        player = await self._get_json("/x/player/v2", bvid=bvid, cid=cid)
        player_data = player.get("data") or {}
        points = tuple(int(item.get("from", 0) * 1000) for item in player_data.get("view_points", []) if item.get("from") is not None)
        return BilibiliSourceMeta(
            bvid=bvid,
            cid=cid,
            duration_ms=int(data.get("duration", 0)) * 1000,
            view_points=points,
            preview_toast=str(player_data.get("preview_toast", "")),
        )

    async def fetch_comments(self, cid: int) -> bytes:
        headers = {"User-Agent": "Mozilla/5.0 (danmu-autopilot; authorized client)"}
        if self._cookie:
            headers["Cookie"] = self._cookie
        response = await self._client.get(
            "https://api.bilibili.com/x/v2/dm/web/seg.so",
            params={"oid": cid, "type": 1, "segment_index": 1},
            headers=headers,
        )
        response.raise_for_status()
        body = await response.aread()
        # The real endpoint is protobuf.  Test doubles and entitlement errors may
        # return JSON; inspect only that explicit shape and never retry/bypass it.
        if body.lstrip().startswith(b"{"):
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if int(payload.get("code", 0)) in {-403, -10403}:
                raise SourceAccessDenied(str(payload.get("message", "source access denied")))
            data = payload.get("data")
            return data.encode() if isinstance(data, str) else body
        return body
