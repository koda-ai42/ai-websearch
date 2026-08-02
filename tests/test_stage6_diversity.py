import json
import socket
import sqlite3
from pathlib import Path

from benchmarks.stage6 import POLICIES, _evidence_metrics, _select, run_stage6_benchmark


def test_stage6_is_deterministic_offline_and_has_separate_metric_families() -> None:
    first = run_stage6_benchmark()
    assert first == run_stage6_benchmark()
    assert set(first["policies"]) == set(POLICIES)
    for result in first["policies"].values():
        assert {"accuracy", "diversity", "corroboration", "reliability", "latency"} <= result.keys()
    assert first["live_integrations_executed"] == []
    assert (
        first["evaluation_protocol"]["database_access"]
        == "No database is opened by Stage 6 replay."
    )


def test_duplicate_evidence_receives_credit_only_once() -> None:
    baseline = run_stage6_benchmark()["policies"]["score_order_baseline"]
    canonical_case = next(case for case in baseline["cases"] if case["id"] == "canonical_aliases")
    assert canonical_case["selected_ids"] == ["ca1", "ca2", "ca3"]
    assert canonical_case["evidence_precision"] == 1 / 3
    assert canonical_case["evidence_recall"] == 0.5


def test_each_hard_diversity_policy_enforces_its_own_identity() -> None:
    policies = run_stage6_benchmark()["policies"]
    canonical = next(
        case for case in policies["canonical_dedup"]["cases"] if case["id"] == "canonical_aliases"
    )
    source = next(
        case for case in policies["source_dedup"]["cases"] if case["id"] == "source_crowding"
    )
    domain = next(
        case for case in policies["domain_dedup"]["cases"] if case["id"] == "domain_corroboration"
    )
    assert canonical["unique_canonical_urls"] == 3
    assert source["unique_sources"] == 3
    assert domain["unique_domains"] == 3


def test_diversity_reports_corroboration_displacement_explicitly() -> None:
    policies = run_stage6_benchmark()["policies"]
    assert policies["score_order_baseline"]["corroboration"]["retention_rate"] == 1.0
    assert policies["domain_dedup"]["corroboration"]["displaced_count"] > 0
    assert (
        policies["near_duplicate_penalty"]["diversity"]["near_duplicate_rate"]
        <= policies["score_order_baseline"]["diversity"]["near_duplicate_rate"]
    )


def test_per_source_cap_is_less_restrictive_than_source_dedup() -> None:
    policies = run_stage6_benchmark()["policies"]
    cap = policies["per_source_cap_2"]
    dedup = policies["source_dedup"]
    assert cap["accuracy"]["evidence_recall"] >= dedup["accuracy"]["evidence_recall"]


def test_stage6_replay_is_network_and_database_free(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise AssertionError("Stage 6 offline benchmark attempted external I/O")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    assert run_stage6_benchmark() == run_stage6_benchmark()


def test_checked_in_stage6_result_matches_replay() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "stage6-diversity-policy-results.json"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == run_stage6_benchmark()


def test_ndcg_ideal_uses_requested_cutoff_when_selection_is_short() -> None:
    selected = [{"evidence_id": "a"}]
    metrics = _evidence_metrics(selected, {"a", "b", "c"}, cutoff=3)
    assert 0.0 < metrics["ndcg"] < 1.0


def test_adjusted_utility_ties_keep_baseline_id_order() -> None:
    def chunk(identifier: str, score: float) -> dict:
        return {
            "id": identifier,
            "score": score,
            "source_id": identifier,
            "canonical_url": f"https://example.test/{identifier}",
            "domain": "example.test",
            "near_group": identifier,
            "evidence_id": identifier,
            "text": "identical words",
        }

    case = {"top_k": 2, "chunks": [chunk("a", 1.0), chunk("b", 0.8), chunk("c", 0.8)]}
    for policy in ("near_duplicate_penalty", "marginal_novelty"):
        selected, _ = _select(case, policy)
        assert [item["id"] for item in selected] == ["a", "b"]
