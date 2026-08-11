"""Deterministic metadata and timeline anomaly evidence extraction."""

from __future__ import annotations

from collections.abc import Sequence

from .domain import Comment, Evidence, SourceMeta, WorkMeta


def _evidence(kind: str, score: float, time_ms: int | None = None, detail: str = "") -> Evidence:
    return Evidence(kind=kind, score=max(0.0, min(1.0, score)), time_ms=time_ms, detail=detail, metadata={})


def extract_signals(
    comments: Sequence[Comment], source_meta: SourceMeta, work_meta: WorkMeta
) -> tuple[Evidence, ...]:
    result: list[Evidence] = []
    expected_total = max(1, work_meta.episode_count) * max(1, work_meta.expected_episode_ms)
    duration_ratio = source_meta.duration_ms / expected_total
    # A source that is close to the expected total is a useful, but not decisive,
    # fit.  Large ratios often indicate a concatenated upload with pre-roll.
    fit_score = max(0.0, 1.0 - abs(duration_ratio - 1.0) / 0.8)
    if work_meta.episode_count > 1 and duration_ratio > 1.35:
        fit_score = min(1.0, 0.92 + min(0.07, (duration_ratio - 1.35) / 10))
    result.append(_evidence("episode_count_fit", fit_score, detail=f"ratio={duration_ratio:.3f}"))

    if not comments:
        result.append(_evidence("metadata", 0.25, detail="source contains no comments"))
        return tuple(result)

    timestamps = sorted(comment.time_ms for comment in comments)
    bin_ms = 30_000
    first = timestamps[0]
    last = timestamps[-1]
    changes: list[tuple[float, int]] = []
    window_ms = 5 * 60_000
    for boundary in range(((first // bin_ms) + 1) * bin_ms, last, bin_ms):
        left = sum(1 for timestamp in timestamps if boundary - window_ms <= timestamp < boundary)
        right = sum(1 for timestamp in timestamps if boundary <= timestamp < boundary + window_ms)
        if right > max(1, left) * 2 and right >= 3:
            aligned = next((timestamp for timestamp in timestamps if timestamp >= boundary), boundary)
            changes.append((right / max(1.0, left), aligned))
    if changes:
        # Select the first robust discontinuity; later episode boundaries may
        # have the same density ratio and must not hide the padding boundary.
        ratio, boundary = min(changes, key=lambda item: item[1])
        result.append(_evidence("density_change", min(0.99, 0.55 + ratio / 20), boundary, f"density_ratio={ratio:.2f}"))
    else:
        result.append(_evidence("density_change", 0.15, detail="no robust density boundary"))
    result.append(_evidence("metadata", 0.65, detail=f"comments={len(comments)}"))
    return tuple(result)


def strongest(evidence: Sequence[Evidence], kind: str) -> Evidence:
    candidates = [item for item in evidence if item.kind == kind]
    if not candidates:
        return _evidence(kind, 0.0)
    return max(candidates, key=lambda item: item.score)
