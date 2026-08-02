import json
import socket
import sqlite3
from pathlib import Path

from benchmarks.stage8 import run_stage8_benchmark


def test_stage8_is_deterministic_and_separates_metrics() -> None:
    first = run_stage8_benchmark()
    assert first == run_stage8_benchmark()
    for group in (
        "http_client_policies",
        "browser_lifecycle_policies",
        "embedding_refresh_policies",
        "token_count_policies",
        "vector_scan_policies",
    ):
        for policy in first[group].values():
            assert {"accuracy", "reliability", "latency"} <= policy.keys()
    assert first["live_integrations_executed"] == []


def test_http_reuse_preserves_outcomes_and_closes_owned_clients() -> None:
    policies = run_stage8_benchmark()["http_client_policies"]
    assert (
        policies["per_attempt_client"]["reliability"]["client_instances"]
        > policies["per_operation_client"]["reliability"]["client_instances"]
    )
    assert policies["scoped_batch_client"]["reliability"]["client_instances"] == 1
    for policy in policies.values():
        reliability = policy["reliability"]
        assert reliability["clients_closed"] == reliability["client_instances"]
        assert reliability["cookie_storage_enabled"] is False
        assert policy["accuracy"]["request_outcome_preservation"] == 1.0


def test_browser_reuse_is_ephemeral_isolated_and_counts_real_failures() -> None:
    policies = run_stage8_benchmark()["browser_lifecycle_policies"]
    reused = policies["scoped_ephemeral_browser"]
    assert reused["reliability"]["browser_startups"] == 1
    assert reused["reliability"]["browser_closes"] == 1
    assert reused["reliability"]["actual_crawl_failures"] == 1
    assert reused["reliability"]["isolated_page_context_per_url"] is True
    assert reused["reliability"]["personal_profile"] is False


def test_unchanged_refresh_skips_embedding_without_changing_active_content() -> None:
    policies = run_stage8_benchmark()["embedding_refresh_policies"]
    current = policies["embed_every_successful_refresh"]
    skipped = policies["skip_unchanged_before_embedding"]
    assert (
        skipped["reliability"]["embedding_operations"]
        < current["reliability"]["embedding_operations"]
    )
    assert skipped["accuracy"]["active_content_outcome_preservation"] == 1.0
    assert skipped["reliability"]["failed_refresh_embedded"] is False


def test_token_candidate_removes_only_post_convergence_call() -> None:
    policies = run_stage8_benchmark()["token_count_policies"]
    current = policies["current_stable_plus_final"]
    candidate = policies["stop_on_validated_fixed_point"]
    assert candidate["reliability"]["tokenize_calls"] < current["reliability"]["tokenize_calls"]
    assert candidate["accuracy"]["final_count_consistency"] == 1.0
    assert candidate["reliability"]["final_exact_validation_rate"] == 1.0


def test_vector_models_preserve_exact_top_k_without_claiming_production_justification() -> None:
    result = run_stage8_benchmark()
    for policy in result["vector_scan_policies"].values():
        assert policy["accuracy"]["probe_top_k_preservation"] == 1.0
        assert policy["accuracy"]["scale_top_k_preservation_measured"] is False
        assert all(row["top_k_preserved"] is None for row in policy["sizes"])
        assert policy["reliability"]["full_corpus_examined"] is True
        assert policy["reliability"]["approximate_search"] is False
    assert "cannot justify" in result["evaluation_protocol"]["vector_decision"]


def test_stage8_replay_is_network_and_database_free(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise AssertionError("Stage 8 offline benchmark attempted external I/O")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    assert run_stage8_benchmark() == run_stage8_benchmark()


def test_checked_in_stage8_result_matches_replay() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "stage8-performance-results.json"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == run_stage8_benchmark()
