"""Per-source circuit breaker state with explicit failure categories."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


class FailureKind(StrEnum):
    TRANSIENT = "transient"
    DNS = "dns"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    ACCESS_DENIED = "access_denied"


@dataclass(slots=True)
class _State:
    failures: int = 0
    opened_at: float | None = None
    probe_in_flight: bool = False


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cool_down_seconds: float = 60.0, clock: Callable[[], float] | None = None) -> None:
        self.threshold = max(1, threshold)
        self.cool_down_seconds = max(0.1, cool_down_seconds)
        self.clock = clock or time.monotonic
        self._states: dict[str, _State] = {}

    def _state(self, source: str) -> _State:
        return self._states.setdefault(source, _State())

    def allow(self, source: str, probe: bool = False) -> bool:
        state = self._state(source)
        if state.opened_at is None:
            return True
        if self.clock() - state.opened_at < self.cool_down_seconds:
            return False
        if state.probe_in_flight and not probe:
            return False
        state.probe_in_flight = True
        return True

    def record_success(self, source: str) -> None:
        self._states[source] = _State()

    def record_failure(self, source: str, kind: FailureKind) -> None:
        state = self._state(source)
        state.probe_in_flight = False
        # Permanent entitlement denial should be visible but must not cause a
        # retry storm; leave the circuit closed and let policy suppress retries.
        if kind is FailureKind.ACCESS_DENIED:
            return
        state.failures += 1
        if state.failures >= self.threshold:
            state.opened_at = self.clock()
