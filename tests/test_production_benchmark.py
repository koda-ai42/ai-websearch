import json
from pathlib import Path

from benchmarks.production_retrieval import run_production_retrieval_benchmark


def test_production_retrieval_benchmark_is_deterministic_without_timing() -> None:
    result = run_production_retrieval_benchmark()
    assert result == run_production_retrieval_benchmark()
    assert (
        result["accuracy"]["implemented_mean_reciprocal_rank"]
        > result["accuracy"]["legacy_mean_reciprocal_rank"]
    )
    assert result["accuracy"]["fts_implemented_reciprocal_rank"] == 1.0
    assert result["accuracy"]["fts_legacy_reciprocal_rank"] < 1.0
    assert result["reliability"]["network_access"] is False
    assert result["latency"]["measured"] is False


def test_recorded_production_result_matches_accuracy_and_reliability() -> None:
    path = Path(__file__).resolve().parents[1] / "docs/benchmarks/production-retrieval-results.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))
    replay = run_production_retrieval_benchmark()
    assert recorded["accuracy"] == replay["accuracy"]
    assert recorded["reliability"] == replay["reliability"]
    assert recorded["fts"] == replay["fts"]
    assert recorded["fusion_cases"] == replay["fusion_cases"]
