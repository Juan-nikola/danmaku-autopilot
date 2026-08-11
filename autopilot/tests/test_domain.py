from __future__ import annotations

import pytest

from danmu_autopilot.domain import (
    AnalysisResult,
    Comment,
    Confidence,
    Evidence,
    MatchContext,
    Segment,
    SourceCandidate,
)


def test_domain_types_are_immutable_and_typed() -> None:
    comment = Comment(
        time_ms=1000,
        mode=1,
        color=0xFFFFFF,
        size=25,
        text="hello",
        source_id="bilibili",
    )
    segment = Segment(episode=1, source_start_ms=100, source_end_ms=200)
    result = AnalysisResult(
        segments=(segment,),
        score=0.95,
        confidence=Confidence.HIGH,
        evidence=(Evidence(kind="title", score=0.9, detail="exact"),),
    )

    assert comment.source_id == "bilibili"
    assert result.confidence is Confidence.HIGH
    with pytest.raises(AttributeError):
        comment.text = "changed"  # type: ignore[misc]


def test_domain_types_reject_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="time_ms"):
        Comment(
            time_ms=-1,
            mode=1,
            color=0xFFFFFF,
            size=25,
            text="hello",
            source_id="x",
        )

    with pytest.raises(ValueError, match="source_end_ms"):
        Segment(episode=1, source_start_ms=200, source_end_ms=100)


def test_match_context_and_source_candidate_are_serializable() -> None:
    context = MatchContext(
        title="示例",
        year=2024,
        season=1,
        episode=2,
        filename="示例 - 02.mkv",
    )
    candidate = SourceCandidate(
        source_id="misaka",
        title="示例",
        episode=2,
        comments=(
            Comment(
                time_ms=10,
                mode=1,
                color=0,
                size=25,
                text="x",
                source_id="misaka",
            ),
        ),
        score=0.8,
    )

    assert context.episode == 2
    assert candidate.comments[0].text == "x"

