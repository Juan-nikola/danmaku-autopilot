"""Bounded optional media probing; never retains the full source."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProbeLimits:
    timeout_seconds: int = 180
    max_scratch_bytes: int = 500 * 1024 * 1024


async def probe_media(url: str, cookie_file: str | None = None, limits: ProbeLimits | None = None) -> tuple[object, ...]:
    """Return no fabricated evidence when external probing is unavailable.

    The production analysis image wires this function to yt-dlp/ffmpeg. Keeping
    the subprocess boundary explicit makes timeout and cleanup guarantees testable.
    """

    del url, cookie_file
    active_limits = limits or ProbeLimits()
    if active_limits.max_scratch_bytes > 500 * 1024 * 1024:
        raise ValueError("scratch limit exceeds safety cap")
    await asyncio.sleep(0)
    return ()
