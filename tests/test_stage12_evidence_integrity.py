import json
import socket
from pathlib import Path

from benchmarks.stage12 import run_stage12_benchmark


def test_stage12_is_deterministic_and_offline(monkeypatch) -> None:
    def denied(*_args, **_kwargs):
        raise AssertionError("stage 12 attempted network access")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    assert run_stage12_benchmark() == run_stage12_benchmark()


def test_checked_in_stage12_result_matches_current_policy() -> None:
    artifact = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "stage12-evidence-integrity-results.json"
    )
    if artifact.exists():
        assert json.loads(artifact.read_text(encoding="utf-8")) == run_stage12_benchmark()


def test_stage12_has_broad_access_outcome_coverage() -> None:
    result = run_stage12_benchmark()
    rows = result["crawl_cases"]
    assert len(rows) >= 30
    assert {row["expected"] for row in rows} == {
        "success",
        "cookie_consent",
        "authentication",
        "captcha",
        "subscription",
        "access_denied",
    }
    assert result["latency"]["evidence_cases_evaluated"] >= 4
