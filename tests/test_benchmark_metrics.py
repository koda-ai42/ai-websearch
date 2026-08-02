import math

from benchmarks.metrics import (
    duplicate_rate,
    latency_summary,
    ndcg,
    precision_recall,
    reciprocal_rank,
)


def test_ranking_metrics_have_known_values() -> None:
    ranked = ["irrelevant", "relevant", "also-relevant"]
    relevant = {"relevant", "also-relevant"}
    precision, recall = precision_recall(ranked, relevant)
    assert precision == 2 / 3
    assert recall == 1.0
    assert reciprocal_rank(ranked, relevant) == 0.5
    assert 0.0 < ndcg(ranked, relevant) < 1.0


def test_duplicate_and_latency_metrics_are_deterministic() -> None:
    assert duplicate_rate(["Same text", " same   TEXT ", "different"]) == 1 / 3
    summary = latency_summary([1.0, 2.0, 3.0, 100.0])
    assert summary == {"count": 4, "p50_ms": 2.5, "p95_ms": 100.0}
    assert math.isfinite(summary["p50_ms"])
