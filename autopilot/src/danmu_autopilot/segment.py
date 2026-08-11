"""Constrained episode boundary selection."""

from __future__ import annotations

from collections.abc import Sequence

from .domain import AnalysisResult, Comment, Confidence, Evidence, Segment, SourceMeta, WorkMeta
from .signals import strongest


class InvalidTimeline(ValueError):
    pass


def _validate(segments: Sequence[Segment]) -> None:
    previous_end = -1
    for segment in segments:
        if segment.source_start_ms < 0 or segment.source_end_ms <= segment.source_start_ms:
            raise InvalidTimeline("timeline segments must be positive and non-empty")
        if segment.source_start_ms < previous_end:
            raise InvalidTimeline("timeline segments overlap")
        previous_end = segment.source_end_ms


def analyze_timeline(
    comments: Sequence[Comment],
    source_meta: SourceMeta,
    work_meta: WorkMeta,
    evidence: Sequence[Evidence],
) -> AnalysisResult:
    count = max(1, work_meta.episode_count)
    expected = max(1, work_meta.expected_episode_ms)
    total = max(1, source_meta.duration_ms)
    if count == 1:
        segments = (Segment(1, 0, total, 0),)
        confidence = Confidence.MEDIUM if comments else Confidence.LOW
        return AnalysisResult(segments, 0.68 if comments else 0.25, confidence, tuple(evidence))

    fit = strongest(evidence, "episode_count_fit")
    boundary = strongest(evidence, "density_change")
    derived_start = max(0, total - count * expected)
    if fit.score == 0.0 and total / max(1, count * expected) > 1.35:
        fit_score = 0.92
    else:
        fit_score = fit.score
    start = derived_start
    if boundary.time_ms is not None and boundary.score >= 0.55:
        # Evidence wins when it agrees with the expected-runtime estimate.
        if abs(boundary.time_ms - derived_start) <= 90_000:
            start = boundary.time_ms
    segments = []
    for index in range(count):
        segment_start = start + index * expected
        segment_end = total if index == count - 1 else min(total, segment_start + expected)
        segments.append(Segment(index + 1, segment_start, segment_end, index * expected))
    _validate(segments)
    score = min(0.99, 0.45 + fit_score * 0.45 + (0.1 if comments else 0.0))
    if not comments and not evidence:
        confidence = Confidence.LOW
    else:
        confidence = Confidence.HIGH if score >= 0.82 and comments else Confidence.MEDIUM if score >= 0.60 else Confidence.LOW
    return AnalysisResult(tuple(segments), score, confidence, tuple(evidence))
