from danmu_autopilot.domain import Comment, Confidence, SourceMeta, WorkMeta
from danmu_autopilot.segment import analyze_timeline


SOURCE = SourceMeta(duration_ms=17_283_000, pages=1, view_points=())
WORK = WorkMeta(episode_count=8, expected_episode_ms=1_260_000)


def test_strong_two_hour_sample_splits_eight_episodes():
    comments = tuple(
        Comment(7_200_000 + index * 1_260_000, 1, 0xFFFFFF, 25, f"anchor-{index}", "fixture")
        for index in range(8)
    )
    result = analyze_timeline(comments, SOURCE, WORK, evidence=())
    assert result.confidence is Confidence.HIGH
    assert len(result.segments) == 8
    assert abs(result.segments[0].source_start_ms - 7_200_000) <= 30_000
    assert result.segments[-1].source_end_ms == 17_283_000


def test_weak_input_still_returns_best_effort():
    result = analyze_timeline((), SOURCE, WORK, evidence=())
    assert result.confidence is Confidence.LOW
    assert len(result.segments) == 8
