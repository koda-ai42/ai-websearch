import json
import socket
import sqlite3
from pathlib import Path

from benchmarks.stage4 import CACHE_POLICIES, load_stage4_corpus, run_stage4_benchmark


def scenario(policy: dict, scenario_id: str) -> dict:
    return next(item for item in policy["scenarios"] if item["id"] == scenario_id)


def test_stage4_corpus_and_policies_are_versioned() -> None:
    _, corpus = load_stage4_corpus()
    assert corpus["version"] == "2026-07-14.stage4.v1"
    assert set(CACHE_POLICIES) == {
        "current_append_model",
        "replace_active",
        "retain_history_single_active",
    }
    assert {item["id"] for item in corpus["scenarios"]} >= {
        "fresh-cache-hit-before-refresh",
        "unchanged-stale-refresh",
        "changed-content-version",
        "failed-refresh-preserves-good",
        "consent-wall-after-good",
        "standalone-auth-wall",
        "canonical-alias-unchanged",
        "historical-content-reversion",
    }


def test_safe_policies_consult_cache_reject_walls_and_preserve_good_content() -> None:
    result = run_stage4_benchmark()
    for name in ("replace_active", "retain_history_single_active"):
        policy = result["policies"][name]
        assert policy["accuracy"]["scenario_correctness"] == 1.0
        assert policy["accuracy"]["good_content_preservation_rate"] == 1.0
        assert policy["accuracy"]["wall_rejection_rate"] == 1.0
        assert policy["reliability"]["wall_results_cached"] == 0
        assert scenario(policy, "fresh-cache-hit-before-refresh")["cache_hits"] == 1
        assert scenario(policy, "failed-refresh-preserves-good")["active_content_hashes"] == [
            "preserved-good"
        ]
        assert policy["accuracy"]["good_content_preservation_applicable_cases"] == 3
        assert policy["accuracy"]["wall_rejection_applicable_cases"] == 2
        assert policy["accuracy"]["single_active_version_applicable_cases"] == 7
        assert policy["accuracy"]["unchanged_work_avoidance_applicable_cases"] == 3
        assert policy["accuracy"]["cache_before_refresh_applicable_cases"] == 1
        assert scenario(policy, "changed-content-version")["good_content_preserved"] is None


def test_current_model_exposes_late_duplicate_work_and_wall_storage() -> None:
    result = run_stage4_benchmark()
    current = result["policies"]["current_append_model"]
    safe = result["policies"]["retain_history_single_active"]
    assert current["reliability"]["wall_results_cached"] == 2
    assert (
        current["reliability"]["operation_counts"]["embed"]
        > safe["reliability"]["operation_counts"]["embed"]
    )
    assert scenario(current, "unchanged-stale-refresh")["embedding_operations"] == 2
    assert scenario(safe, "unchanged-stale-refresh")["embedding_operations"] == 1
    assert scenario(current, "consent-wall-after-good")["wall_results_cached"] == 1


def test_version_semantics_distinguish_replace_from_retained_history() -> None:
    result = run_stage4_benchmark()
    replaced = scenario(result["policies"]["replace_active"], "changed-content-version")
    retained = scenario(
        result["policies"]["retain_history_single_active"], "changed-content-version"
    )
    current = scenario(result["policies"]["current_append_model"], "changed-content-version")
    assert (replaced["stored_versions"], replaced["active_versions"]) == (1, 1)
    assert (retained["stored_versions"], retained["active_versions"]) == (2, 1)
    assert (current["stored_versions"], current["active_versions"]) == (2, 2)


def test_retained_history_reactivates_reverted_content_as_sole_active_version() -> None:
    result = run_stage4_benchmark()
    replaced = scenario(result["policies"]["replace_active"], "historical-content-reversion")
    retained = scenario(
        result["policies"]["retain_history_single_active"], "historical-content-reversion"
    )
    current = scenario(result["policies"]["current_append_model"], "historical-content-reversion")
    assert retained["active_content_hashes"] == ["revert-v1"]
    assert (
        retained["stored_versions"],
        retained["active_versions"],
        retained["embedding_operations"],
    ) == (2, 1, 2)
    assert (
        replaced["stored_versions"],
        replaced["active_versions"],
        replaced["embedding_operations"],
    ) == (1, 1, 3)
    assert current["active_versions"] == 2


def test_cache_reads_are_distinct_from_writes_and_only_safe_policies_consult_first() -> None:
    result = run_stage4_benchmark()
    current = result["policies"]["current_append_model"]
    assert "cache_read_before_refresh" not in current["reliability"]["operation_counts"]
    for name in ("replace_active", "retain_history_single_active"):
        policy = result["policies"][name]
        assert policy["reliability"]["operation_counts"]["cache_read_before_refresh"] == 16
        assert policy["latency"]["operation_counts"]["database_read"] > 0
    for policy in result["policies"].values():
        assert (
            policy["latency"]["operation_counts"]["database_write"]
            == policy["reliability"]["operation_counts"]["cache_write"]
        )


def test_stage4_replay_is_deterministic_network_free_and_database_free(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise AssertionError("Stage 4 offline benchmark attempted external I/O")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    first = run_stage4_benchmark()
    second = run_stage4_benchmark()
    assert first == second
    assert first["live_integrations_executed"] == []
    assert first["evaluation_protocol"]["database_access"].startswith("No SQLite")
    assert all(policy["latency"]["peak_rss_bytes"] is None for policy in first["policies"].values())


def test_checked_in_stage4_result_matches_replay() -> None:
    result_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "stage4-cache-policy-results.json"
    )
    assert json.loads(result_path.read_text(encoding="utf-8")) == run_stage4_benchmark()
