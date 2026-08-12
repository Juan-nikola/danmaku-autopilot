from danmu_autopilot.domain import Comment, SourceMeta, WorkMeta
from danmu_autopilot.signals import extract_signals, strongest


def _padding_comments():
    comments = [
        Comment(120_000, 1, 0xFFFFFF, 25, "片头", "fixture"),
        Comment(6_900_000, 1, 0xFFFFFF, 25, "等待", "fixture"),
    ]
    for index in range(80):
        comments.append(Comment(7_200_000 + index * 100_000, 1, 0xFFFFFF, 25, f"弹幕{index}", "fixture"))
    return tuple(comments)


def test_two_hour_padding_emits_start_and_eight_episode_fit():
    evidence = extract_signals(
        _padding_comments(),
        SourceMeta(duration_ms=17_283_000, pages=1, view_points=()),
        WorkMeta(episode_count=8, expected_episode_ms=1_260_000),
    )
    assert strongest(evidence, "density_change").time_ms in range(7_180_000, 7_221_000)
    assert strongest(evidence, "episode_count_fit").score >= 0.9


def test_zero_comment_source_returns_low_confidence_metadata():
    evidence = extract_signals(
        (), SourceMeta(duration_ms=1_000, pages=1, view_points=()), WorkMeta(episode_count=1, expected_episode_ms=1_000)
    )
    assert strongest(evidence, "metadata").score < 0.6
