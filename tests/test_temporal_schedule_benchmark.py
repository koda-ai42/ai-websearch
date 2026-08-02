import json
import socket
from pathlib import Path

from benchmarks.temporal_schedule import run_temporal_schedule_benchmark


def test_temporal_schedule_benchmark_is_deterministic_and_offline(monkeypatch) -> None:
    def denied(*_args, **_kwargs):
        raise AssertionError("temporal schedule benchmark attempted network access")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    assert run_temporal_schedule_benchmark() == run_temporal_schedule_benchmark()


def test_checked_in_temporal_schedule_result_matches_current_policy() -> None:
    artifact = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "temporal-schedule-results.json"
    )
    if artifact.exists():
        assert json.loads(artifact.read_text(encoding="utf-8")) == (
            run_temporal_schedule_benchmark()
        )


def test_temporal_schedule_benchmark_reports_separate_metric_families() -> None:
    result = run_temporal_schedule_benchmark()
    assert set(result) >= {"accuracy", "reliability", "latency", "limitations"}
    assert result["latency"]["measured"] is False
    assert all(result["reliability"]["answer_contract_controls"].values())
