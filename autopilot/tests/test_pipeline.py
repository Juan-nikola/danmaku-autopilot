import pytest

from danmu_autopilot.pipeline import AutopilotPipeline
from danmu_autopilot.store import JobStore


@pytest.mark.asyncio
async def test_pipeline_normalizes_first_match_and_keeps_low_confidence_automatic(tmp_path):
    store = JobStore(tmp_path / "autopilot.db")
    await store.initialize()
    job = await store.enqueue("pipeline-key", {"fileName": "Show.S01E02.1080p.mkv"})
    pipeline = AutopilotPipeline(store)
    outcome = await pipeline.handle(job.id)
    assert outcome.context.title == "Show"
    assert outcome.context.episode == 2
    assert outcome.status == "candidate_search"
    assert outcome.automatic is True
    await store.close()
