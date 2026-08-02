from __future__ import annotations

import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from .metrics import latency_summary

STAGES = (
    "query_planning",
    "search_request",
    "search_merge_dedup",
    "crawl_extraction",
    "cleaning",
    "chunking",
    "embedding_load",
    "embedding_encode",
    "database_write",
    "fts",
    "vector_scan",
    "normalization_fusion",
    "diversity_selection",
    "rendering",
    "llama_props",
    "llama_tokenize",
    "total",
)


@dataclass(frozen=True)
class TraceEvent:
    stage: str
    duration_ms: float
    ok: bool = True


class StageTracer:
    """Benchmark-only timing collector; production modules do not import it."""

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        stages: tuple[str, ...] = STAGES,
    ) -> None:
        self._clock = clock
        self._stages = stages
        self.events: list[TraceEvent] = []

    def record(self, stage: str, duration_ms: float, ok: bool = True) -> None:
        if stage not in self._stages:
            raise ValueError(f"unknown benchmark stage: {stage}")
        if duration_ms < 0:
            raise ValueError("duration must not be negative")
        self.events.append(TraceEvent(stage, float(duration_ms), ok))

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        started = self._clock()
        ok = False
        try:
            yield
            ok = True
        finally:
            self.record(stage, (self._clock() - started) * 1000.0, ok)

    def summary(self, peak_rss_bytes: int | None = None) -> dict:
        durations: dict[str, list[float]] = defaultdict(list)
        operations: Counter[str] = Counter()
        failures: Counter[str] = Counter()
        for event in self.events:
            durations[event.stage].append(event.duration_ms)
            operations[event.stage] += 1
            if not event.ok:
                failures[event.stage] += 1
        return {
            "stages": {stage: latency_summary(durations.get(stage, [])) for stage in self._stages},
            "operation_counts": dict(sorted(operations.items())),
            "failure_counts": dict(sorted(failures.items())),
            "peak_rss_bytes": peak_rss_bytes,
        }
