from danmu_autopilot.circuit import CircuitBreaker, FailureKind


def test_breaker_opens_then_half_opens():
    now = [100.0]
    breaker = CircuitBreaker(threshold=3, cool_down_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        breaker.record_failure("bilibili", FailureKind.TRANSIENT)
    assert not breaker.allow("bilibili")
    now[0] += 61
    assert breaker.allow("bilibili", probe=True)
