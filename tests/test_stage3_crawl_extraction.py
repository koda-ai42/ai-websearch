import json
import socket
from pathlib import Path

from benchmarks.stage3 import (
    EXTRACTION_POLICIES,
    OUTCOMES,
    classify_outcome,
    load_stage3_corpus,
    run_stage3_benchmark,
    select_markdown,
)


def cases_by_id() -> dict[str, dict]:
    _, corpus = load_stage3_corpus()
    return {case["id"]: case for case in corpus["cases"]}


def test_stage3_corpus_covers_every_required_outcome() -> None:
    _, corpus = load_stage3_corpus()
    assert corpus["version"] == "2026-07-14.stage3.v1"
    assert {case["expected_outcome"] for case in corpus["cases"]} == OUTCOMES


def test_markdown_orders_evaluate_all_available_variants() -> None:
    case = cases_by_id()["article-fit-preferred"]
    assert (
        select_markdown(case, EXTRACTION_POLICIES["current_behavior_model"].markdown_order)[0]
        == "direct"
    )
    assert (
        select_markdown(case, EXTRACTION_POLICIES["explicit_fit_first"].markdown_order)[0] == "fit"
    )
    assert (
        select_markdown(case, EXTRACTION_POLICIES["explicit_raw_first"].markdown_order)[0] == "raw"
    )
    assert (
        select_markdown(case, EXTRACTION_POLICIES["explicit_citations_first"].markdown_order)[0]
        == "citations"
    )


def test_explicit_classifier_distinguishes_access_outcomes() -> None:
    for case in cases_by_id().values():
        _, markdown = select_markdown(
            case, EXTRACTION_POLICIES["explicit_fit_first"].markdown_order
        )
        assert classify_outcome(case, markdown, explicit=True) == case["expected_outcome"]


def test_current_model_exposes_wall_acceptance_and_explicit_model_rejects_it() -> None:
    result = run_stage3_benchmark()
    current = result["extraction_policies"]["current_behavior_model"]
    explicit = result["extraction_policies"]["explicit_fit_first"]
    assert current["accuracy"]["wall_rejection_rate"] == 0.0
    assert current["reliability"]["wall_pages_accepted_as_success"] == 5
    assert explicit["accuracy"]["outcome_classification_accuracy"] == 1.0
    assert explicit["accuracy"]["wall_rejection_rate"] == 1.0
    assert explicit["reliability"]["wall_pages_accepted_as_success"] == 0


def test_trace_failures_follow_fixture_crawl_result_not_classifier_agreement() -> None:
    result = run_stage3_benchmark()
    for policy in result["extraction_policies"].values():
        assert policy["reliability"]["fixture_crawl_failures"] == 1
        assert policy["latency"]["failure_counts"] == {"crawl_extraction": 1}


def test_scoped_lifecycle_is_ephemeral_read_only_and_uses_one_instance() -> None:
    result = run_stage3_benchmark()
    fresh = result["lifecycle_policies"]["fresh_per_url"]
    scoped = result["lifecycle_policies"]["scoped_ephemeral"]
    assert fresh["reliability"]["browser_instances"] == 11
    assert scoped["reliability"]["browser_instances"] == 1
    assert scoped["reliability"]["profile_mode"] == "ephemeral"
    assert scoped["reliability"]["persistent_profile_used"] is False
    assert scoped["reliability"]["personal_profile_used"] is False
    assert scoped["reliability"]["browser_actions"] == "read_only_fixture_replay"
    assert fresh["accuracy"]["expected_outcome_preservation"] is None
    assert scoped["accuracy"]["expected_outcome_preservation"] is None
    assert (
        scoped["latency"]["stages"]["crawl_extraction"]["p50_ms"]
        < fresh["latency"]["stages"]["crawl_extraction"]["p50_ms"]
    )


def test_stage3_replay_is_deterministic_and_network_free(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise AssertionError("Stage 3 offline benchmark attempted network access")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    first = run_stage3_benchmark()
    second = run_stage3_benchmark()
    assert first == second
    assert first["live_integrations_executed"] == []
    assert all(
        policy["latency"]["peak_rss_bytes"] is None
        for policy in first["extraction_policies"].values()
    )


def test_checked_in_stage3_result_matches_replay() -> None:
    result_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "stage3-crawl-extraction-results.json"
    )
    assert json.loads(result_path.read_text(encoding="utf-8")) == run_stage3_benchmark()
