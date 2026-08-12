"""Stable release selection and immutable image-lock contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any

_PRERELEASE_WORDS = re.compile(r"(?:alpha|beta|rc|preview|dev)", re.I)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _version(tag: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", tag)
    return tuple(int(number) for number in numbers[:3]) or (0,)


def select_latest_stable(releases: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        release
        for release in releases
        if not release.get("draft")
        and not release.get("prerelease")
        and not _PRERELEASE_WORDS.search(str(release.get("tag_name", "")))
    ]
    if not candidates:
        raise ValueError("no stable release available")
    return max(candidates, key=lambda release: _version(str(release.get("tag_name", ""))))


@dataclass(frozen=True, slots=True)
class ImageLock:
    misaka_release: str | None = None
    misaka_image: str = "l429609201/misaka_danmu_server"
    misaka_digest: str | None = None
    danmu_api_image: str = "logvar/danmu-api"
    danmu_api_digest: str | None = None
    mysql_image: str = "mysql:8.1.0-oracle"
    autopilot_image: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("misaka_digest", "danmu_api_digest"):
            value = getattr(self, field_name)
            if value is not None and not _DIGEST.fullmatch(value):
                raise ValueError(f"{field_name} must be an immutable sha256 digest")

    def validate_for_deploy(self) -> None:
        if not self.misaka_digest or not self.danmu_api_digest:
            raise ValueError("both Misaka and danmu_api images require sha256 digests")
        if self.mysql_image != "mysql:8.1.0-oracle":
            raise ValueError("MySQL image is pinned to mysql:8.1.0-oracle")

    @property
    def misaka_ref(self) -> str:
        return f"{self.misaka_image}@{self.misaka_digest}" if self.misaka_digest else self.misaka_image

    @property
    def danmu_api_ref(self) -> str:
        return f"{self.danmu_api_image}@{self.danmu_api_digest}" if self.danmu_api_digest else self.danmu_api_image
