import json
import socket
from pathlib import Path

from benchmarks.search_policies import POLICIES, merge_results, plan_queries
from benchmarks.stage2 import load_stage2_corpus, run_stage2_benchmark


def cases_by_id() -> dict[str, dict]:
    _, corpus = load_stage2_corpus()
    return {case["id"]: case for case in corpus["cases"]}


def test_stage2_corpus_and_policy_set_are_versioned() -> None:
    _, corpus = load_stage2_corpus()
    assert corpus["version"] == "2026-07-14.stage2.v1"
    assert set(POLICIES) == {
        "original_only",
        "existing_suffix_expansion",
        "query_type_aware_expansion",
        "per_query_rrf",
        "canonical_dedup",
        "canonical_dedup_domain_cap",
    }


def test_query_type_planner_uses_category_specific_variants() -> None:
    cases = cases_by_id()
    policy = POLICIES["query_type_aware_expansion"]
    assert plan_queries(cases["current-event-aware"], policy)[1].endswith("latest")
    assert plan_queries(cases["consumer-analysis-aware"], policy)[1].endswith(
        "independent analysis"
    )
    assert plan_queries(cases["multi-hop-primary"], policy)[1].endswith("primary source")
    assert plan_queries(cases["canonical-domain-crowding"], policy) == ["example protocol overview"]


def test_rrf_prevents_cross_query_raw_score_scale_from_controlling_rank() -> None:
    case = cases_by_id()["raw-score-scale"]
    result_sets = [
        case["search"][query] for query in plan_queries(case, POLICIES["existing_suffix_expansion"])
    ]
    raw = merge_results(result_sets, POLICIES["existing_suffix_expansion"])
    fused = merge_results(result_sets, POLICIES["per_query_rrf"])
    assert raw[0]["canonical_url"] == "https://agency.example/about"
    assert fused[0]["canonical_url"] == "https://science.example/jupiter"


def test_canonical_dedup_and_domain_cap_are_explicit() -> None:
    case = cases_by_id()["canonical-domain-crowding"]
    queries = plan_queries(case, POLICIES["existing_suffix_expansion"])
    result_sets = [case["search"][query] for query in queries]
    raw = merge_results(result_sets, POLICIES["existing_suffix_expansion"])
    canonical = merge_results(result_sets, POLICIES["canonical_dedup"])
    capped = merge_results(result_sets, POLICIES["canonical_dedup_domain_cap"])
    assert (
        len([item for item in raw if item["canonical_url"] == "https://reference.example/protocol"])
        == 2
    )
    assert (
        len(
            [
                item
                for item in canonical
                if item["canonical_url"] == "https://reference.example/protocol"
            ]
        )
        == 1
    )
    assert len([item for item in capped if "crowded.example" in item["canonical_url"]]) == 2


def test_stage2_replay_is_deterministic_and_network_free(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise AssertionError("Stage 2 offline benchmark attempted network access")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    first = run_stage2_benchmark()
    second = run_stage2_benchmark()
    assert first == second
    assert first["live_integrations_executed"] == []
    assert all(
        set(result) == {"accuracy", "reliability", "latency", "cases"}
        for result in first["policies"].values()
    )
    assert all(result["latency"]["peak_rss_bytes"] is None for result in first["policies"].values())
    assert all(
        0.0 <= result["accuracy"][metric] <= 1.0
        for result in first["policies"].values()
        for metric in (
            "search_precision",
            "search_recall",
            "mrr",
            "ndcg",
            "canonical_duplicate_rate",
        )
    )


def test_checked_in_stage2_result_matches_replay() -> None:
    baseline = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "benchmarks"
        / "stage2-search-policy-results.json"
    )
    assert json.loads(baseline.read_text(encoding="utf-8")) == run_stage2_benchmark()
