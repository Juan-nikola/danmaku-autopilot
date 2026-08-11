"""Small immutable contracts shared by matching and transformation stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_unit_interval(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class Comment:
    time_ms: int
    mode: int
    color: int
    size: int
    text: str
    source_id: str

    def __post_init__(self) -> None:
        _require_non_negative("time_ms", self.time_ms)
        if not 0 <= self.color <= 0xFFFFFF:
            raise ValueError("color must be a 24-bit RGB integer")
        if self.size <= 0:
            raise ValueError("size must be positive")
        if not self.text:
            raise ValueError("text must not be empty")
        if not self.source_id:
            raise ValueError("source_id must not be empty")


@dataclass(frozen=True, slots=True)
class MatchContext:
    filename: str = ""
    title: str = ""
    season: int | None = None
    episode: int | None = None
    year: int | None = None
    aliases: tuple[str, ...] = ()
    # ``original_filename`` is retained for adapters that use that spelling;
    # it is normalized to the canonical ``filename`` in ``__post_init__``.
    original_filename: str | None = None

    def __post_init__(self) -> None:
        filename = self.filename or self.original_filename or ""
        original = self.original_filename or filename
        object.__setattr__(self, "filename", filename)
        object.__setattr__(self, "original_filename", original)
        object.__setattr__(self, "aliases", tuple(dict.fromkeys(self.aliases)))
        if self.season is not None and self.season < 1:
            raise ValueError("season must be positive")
        if self.episode is not None and self.episode < 1:
            raise ValueError("episode must be positive")
        if self.year is not None and not 1800 <= self.year <= 3000:
            raise ValueError("year is outside the supported range")


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    source_id: str
    title: str
    episode: int | None = None
    comments: tuple[Comment, ...] = ()
    score: float = 0.0
    source_url: str | None = None
    latency_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id must not be empty")
        if self.episode is not None and self.episode < 1:
            raise ValueError("episode must be positive")
        _require_unit_interval("score", self.score)
        if self.latency_ms is not None:
            _require_non_negative("latency_ms", self.latency_ms)
        object.__setattr__(self, "comments", tuple(self.comments))


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    score: float
    time_ms: int | None = None
    detail: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("kind must not be empty")
        _require_unit_interval("score", self.score)
        if self.time_ms is not None:
            _require_non_negative("time_ms", self.time_ms)


@dataclass(frozen=True, slots=True)
class Segment:
    episode: int
    source_start_ms: int
    source_end_ms: int
    target_start_ms: int = 0

    def __post_init__(self) -> None:
        if self.episode < 1:
            raise ValueError("episode must be positive")
        _require_non_negative("source_start_ms", self.source_start_ms)
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("source_end_ms must be greater than source_start_ms")
        _require_non_negative("target_start_ms", self.target_start_ms)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    segments: tuple[Segment, ...]
    score: float
    confidence: Confidence
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        _require_unit_interval("score", self.score)
        object.__setattr__(self, "segments", tuple(self.segments))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class SourceMeta:
    duration_ms: int
    pages: int = 0
    view_points: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _require_non_negative("duration_ms", self.duration_ms)
        _require_non_negative("pages", self.pages)
        object.__setattr__(self, "view_points", tuple(self.view_points))


@dataclass(frozen=True, slots=True)
class WorkMeta:
    episode_count: int
    expected_episode_ms: int

    def __post_init__(self) -> None:
        if self.episode_count < 1:
            raise ValueError("episode_count must be positive")
        if self.expected_episode_ms <= 0:
            raise ValueError("expected_episode_ms must be positive")


__all__ = [
    "AnalysisResult",
    "Comment",
    "Confidence",
    "Evidence",
    "MatchContext",
    "Segment",
    "SourceCandidate",
    "SourceMeta",
    "WorkMeta",
]
