"""Automatic primary/backup engine routing with a small circuit breaker."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class EngineRequest:
    method: str
    path: str
    body: bytes = b""
    headers: tuple[tuple[bytes, bytes], ...] = ()
    query: str = ""


@dataclass(frozen=True, slots=True)
class ResponseData:
    status_code: int
    headers: tuple[tuple[bytes, bytes], ...]
    body: bytes
    engine: str | None = None

    def with_engine(self, engine: str) -> "ResponseData":
        # EngineRouter itself remains byte/header transparent.  The public
        # gateway may add an informational header at its outer boundary.
        return replace(self, engine=engine)


class Engine(Protocol):
    async def proxy(self, request: EngineRequest) -> ResponseData: ...


@dataclass(frozen=True, slots=True)
class EngineDecision:
    engine: str
    reason: str


@dataclass(slots=True)
class _Circuit:
    failures: int = 0
    opened_at: float = 0.0

    def is_open(self, now: float, cooldown: float) -> bool:
        return self.opened_at > 0 and (now - self.opened_at) < cooldown


def _no_match(response: ResponseData) -> bool:
    if not (200 <= response.status_code < 300):
        return True
    try:
        payload = json.loads(response.body or b"{}")
    except (ValueError, TypeError):
        return False
    if isinstance(payload, dict):
        for key in ("isMatched", "matched", "is_matched"):
            if key in payload and payload[key] is False:
                return True
        if payload.get("animeId") in (None, 0, "") and any(key in payload for key in ("isMatched", "matched")):
            return True
    return False


class EngineRouter:
    def __init__(self, misaka: Engine, danmu_api: Engine, *, cooldown_seconds: float = 30.0, failure_threshold: int = 2) -> None:
        self.misaka = misaka
        self.danmu_api = danmu_api
        self.cooldown_seconds = cooldown_seconds
        self.failure_threshold = max(1, failure_threshold)
        self._circuits = {"misaka": _Circuit(), "danmu_api": _Circuit()}

    def _healthy(self, engine: str) -> bool:
        return not self._circuits[engine].is_open(time.monotonic(), self.cooldown_seconds)

    def _record_success(self, engine: str) -> None:
        self._circuits[engine] = _Circuit()

    def _record_failure(self, engine: str) -> None:
        circuit = self._circuits[engine]
        circuit.failures += 1
        if circuit.failures >= self.failure_threshold:
            circuit.opened_at = time.monotonic()

    async def route(self, request: EngineRequest, context: Any | None = None) -> EngineDecision:
        del context
        if self._healthy("misaka"):
            return EngineDecision("misaka", "primary")
        if self._healthy("danmu_api"):
            return EngineDecision("danmu_api", "primary-circuit-open")
        # Prefer the primary after both cooldowns expire; this allows recovery.
        return EngineDecision("misaka", "all-circuits-open-probe")

    async def proxy(self, method: str, path: str, body: bytes = b"", *, headers: Any = (), query: str = "", context: Any | None = None) -> ResponseData:
        request = EngineRequest(method.upper(), path, body, tuple(headers.items()) if isinstance(headers, dict) else tuple(headers), query)
        decision = await self.route(request, context)
        primary_name = decision.engine
        primary = self.misaka if primary_name == "misaka" else self.danmu_api
        backup_name = "danmu_api" if primary_name == "misaka" else "misaka"
        backup = self.danmu_api if backup_name == "danmu_api" else self.misaka

        try:
            result = await primary.proxy(request)
            self._record_success(primary_name)
        except Exception:
            self._record_failure(primary_name)
            result = None

        if result is not None and not _no_match(result):
            return result.with_engine(primary_name)

        if not self._healthy(backup_name):
            if result is not None:
                return result.with_engine(primary_name)
            # Probe the backup once even while its circuit is open.  A transient
            # outage should not permanently strand a recovered engine.
        try:
            backup_result = await backup.proxy(request)
            self._record_success(backup_name)
            if result is None or not _no_match(backup_result):
                return backup_result.with_engine(backup_name)
        except Exception:
            self._record_failure(backup_name)
        if result is not None:
            return result.with_engine(primary_name)
        raise RuntimeError("both danmaku engines are unavailable")
