import pytest

from benchmarks.trace import STAGES, StageTracer


class Clock:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


def test_measure_records_success_and_failure() -> None:
    tracer = StageTracer(clock=Clock([1.0, 1.125, 2.0, 2.25]))
    with tracer.measure("fts"):
        pass
    with pytest.raises(RuntimeError):
        with tracer.measure("vector_scan"):
            raise RuntimeError("fixture failure")
    assert tracer.events[0].duration_ms == 125.0
    assert tracer.events[0].ok is True
    assert tracer.events[1].duration_ms == 250.0
    assert tracer.events[1].ok is False


def test_summary_includes_every_required_stage() -> None:
    tracer = StageTracer()
    tracer.record("search_request", 3.5)
    summary = tracer.summary(peak_rss_bytes=1234)
    assert tuple(summary["stages"]) == STAGES
    assert summary["operation_counts"] == {"search_request": 1}
    assert summary["peak_rss_bytes"] == 1234


def test_summary_does_not_invent_peak_rss() -> None:
    assert StageTracer().summary()["peak_rss_bytes"] is None
