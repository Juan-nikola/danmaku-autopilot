import asyncio

import pytest

from danmu_autopilot.store import JobStore


@pytest.mark.asyncio
async def test_same_match_is_enqueued_once(tmp_path):
    store = JobStore(tmp_path / "autopilot.db")
    await store.initialize()
    first = await store.enqueue("match-key", {"fileName": "Show.S01E01.mkv"})
    second = await store.enqueue("match-key", {"fileName": "Show.S01E01.mkv"})
    assert first.id == second.id
    await store.close()


@pytest.mark.asyncio
async def test_running_job_is_reclaimed_after_lease(tmp_path):
    now = [100.0]
    store = JobStore(tmp_path / "autopilot.db", clock=lambda: now[0])
    await store.initialize()
    job = await store.enqueue("lease-key", {"fileName": "Show.mkv"})
    claimed = await store.claim(worker="one", lease_seconds=1)
    assert claimed and claimed.id == job.id
    now[0] += 2
    reclaimed = await store.claim(worker="two", lease_seconds=30)
    assert reclaimed and reclaimed.id == job.id
    await store.close()
