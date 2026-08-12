"""Automatic match-analysis state machine entry point.

The first stage is deliberately fail-open: a normal player response is never
blocked while the background job normalizes and scores a suspicious match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .domain import Confidence, MatchContext
from .normalize import parse_match_context
from .store import JobStore


@dataclass(frozen=True, slots=True)
class JobOutcome:
    status: str
    context: MatchContext
    confidence: Confidence = Confidence.LOW
    automatic: bool = True
    detail: str = ""


class AutopilotPipeline:
    def __init__(self, store: JobStore) -> None:
        self.store = store

    async def handle(self, job_id: str) -> JobOutcome:
        job = await self.store.get(job_id)
        if job is None:
            raise KeyError(job_id)
        filename = str(job.payload.get("fileName") or job.payload.get("filename") or "")
        context = parse_match_context(filename)
        # Matching/correction workers may continue from this state.  It remains
        # automatic even at low confidence; a notification/rule can be emitted
        # later without requiring a human click.
        return JobOutcome("candidate_search", context, Confidence.LOW, True, "awaiting source candidates")
