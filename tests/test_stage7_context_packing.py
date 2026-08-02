import json
import socket
import sqlite3
from pathlib import Path

from benchmarks.stage7 import POLICIES, run_stage7_benchmark


def case(policy: dict, case_id: str) -> dict:
    return next(item for item in policy["cases"] if item["id"] == case_id)


def test_stage7_is_deterministic_and_separates_metrics() -> None:
    first = run_stage7_benchmark()
    assert first == run_stage7_benchmark()
    assert set(first["policies"]) == set(POLICIES)
    for policy in first["policies"].values():
        assert {"accuracy", "packing", "reliability", "latency"} <= policy.keys()
        assert policy["reliability"]["token_budget_violations"] == 0
        assert policy["reliability"]["live_llama_tokenize_executed"] is False
    assert first["live_integrations_executed"] == []


def test_phase1_and_current_baselines_model_documented_caps() -> None:
    policies = run_stage7_benchmark()["policies"]
    phase1 = case(policies["phase1_eight_12000_chars"], "focused_fact")
    current = case(policies["current_balanced_25"], "focused_fact")
    assert phase1["chunks_packed"] <= 8
    assert phase1["characters_packed"] <= 12000
    assert current["effective_max_chunks"] == 7
    assert current["effective_max_sources"] == 3
    assert current["chunks_packed"] <= 7


def test_safety_ceiling_is_never_a_fill_target() -> None:
    policies = run_stage7_benchmark()["policies"]
    candidate = case(policies["combined_candidate_cap_6"], "focused_fact")
    assert candidate["unused_token_budget"] > 0
    assert candidate["answer_readiness"] is True
    assert candidate["chunks_packed"] == 2


def test_conservative_cap_is_derived_from_cap_only_results() -> None:
    result = run_stage7_benchmark()
    analysis = result["cap_analysis"]
    assert analysis["fixture_derived_balanced_cap"] == 6
    assert analysis["production_decision"] is False
    recalls = {
        cap: result["policies"][f"balanced_cap_{cap}"]["accuracy"]["answer_evidence_recall"]
        for cap in analysis["evaluated_caps"]
    }
    assert recalls[6] == max(recalls.values())


def test_no_answer_metrics_are_separate_and_applicable_counts_are_explicit() -> None:
    policy = run_stage7_benchmark()["policies"]["relevance_floor_0_65"]
    no_answer = case(policy, "low_confidence_no_answer")
    assert no_answer["answer_chunk_precision"] is None
    assert no_answer["answer_evidence_recall"] is None
    assert no_answer["abstention_success"] is True
    assert policy["accuracy"]["abstention_success_applicable_cases"] == 1
    assert policy["accuracy"]["answer_evidence_recall_applicable_cases"] == 4


def test_rendered_overhead_is_charged_to_token_and_phase1_character_budgets() -> None:
    policies = run_stage7_benchmark()["policies"]
    current = case(policies["current_balanced_25"], "budget_pressure")
    phase1 = case(policies["phase1_eight_12000_chars"], "focused_fact")
    assert current["tokens_packed"] == 630
    assert current["chunks_packed"] == 1
    assert phase1["characters_packed"] > sum((720, 760))


def test_precision_counts_relevant_corroborating_chunks_consistently() -> None:
    policy = run_stage7_benchmark()["policies"]["combined_candidate_cap_6"]
    focused = case(policy, "focused_fact")
    assert focused["selected_ids"] == ["ff1", "ff2"]
    assert focused["answer_chunk_precision"] == 1.0


def test_conflict_and_corroboration_are_measured_separately() -> None:
    policies = run_stage7_benchmark()["policies"]
    aware = case(policies["explicit_conflict_corroboration"], "explicit_conflict")
    assert aware["conflict_coverage"] == 1.0
    assert aware["corroboration_coverage"] == 0.5
    assert (
        policies["explicit_conflict_corroboration"]["accuracy"][
            "conflict_coverage_applicable_cases"
        ]
        == 1
    )


def test_stage7_replay_is_network_and_database_free(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise AssertionError("Stage 7 offline benchmark attempted external I/O")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    assert run_stage7_benchmark() == run_stage7_benchmark()


def test_checked_in_stage7_result_matches_replay() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "stage7-context-packing-results.json"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == run_stage7_benchmark()
