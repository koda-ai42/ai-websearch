import json
import socket
from pathlib import Path

from benchmarks.corpus import REQUIRED_CATEGORIES, load_corpus
from benchmarks.replay import run_offline_benchmark


def test_versioned_corpus_covers_required_categories() -> None:
    corpus = load_corpus()
    assert corpus.version == "2026-07-14.v1"
    assert {case["category"] for case in corpus.cases} >= REQUIRED_CATEGORIES


def test_offline_replay_is_deterministic_and_network_free(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise AssertionError("offline benchmark attempted network access")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    first = run_offline_benchmark()
    second = run_offline_benchmark()
    assert first == second
    assert first["run_mode"] == "offline_replay"
    assert first["live_integrations_executed"] == []
    assert set(first["pipelines"]) == {"phase1", "current"}


def test_result_separates_metric_families() -> None:
    result = run_offline_benchmark()
    for pipeline in result["pipelines"].values():
        assert set(pipeline) == {"accuracy", "reliability", "latency", "cases"}
        assert "search_precision" in pipeline["accuracy"]
        assert "crawl_outcomes" in pipeline["reliability"]
        assert set(pipeline["latency"]) == {"cold", "warm"}
        assert pipeline["latency"]["cold"]["peak_rss_bytes"] is None
        assert pipeline["latency"]["warm"]["peak_rss_bytes"] is None


def test_cold_embedding_load_occurs_once_per_pipeline_run() -> None:
    result = run_offline_benchmark()
    for pipeline in result["pipelines"].values():
        assert pipeline["latency"]["cold"]["operation_counts"]["embedding_load"] == 1
        assert "embedding_load" not in pipeline["latency"]["warm"]["operation_counts"]


def test_no_answer_case_is_excluded_from_citation_support() -> None:
    result = run_offline_benchmark()
    for pipeline in result["pipelines"].values():
        no_answer = next(case for case in pipeline["cases"] if case["id"] == "no-answer-secret")
        assert no_answer["citation_support"] is None
        assert pipeline["accuracy"]["citation_support_applicable_cases"] == 8


def test_fixture_path_is_inside_benchmark_tree() -> None:
    corpus = load_corpus()
    assert "benchmarks/fixtures" in corpus.path.as_posix()


def test_checked_in_baseline_matches_offline_replay() -> None:
    baseline = (
        Path(__file__).resolve().parents[1] / "docs" / "benchmarks" / "stage1-offline-baseline.json"
    )
    assert json.loads(baseline.read_text(encoding="utf-8")) == run_offline_benchmark()
