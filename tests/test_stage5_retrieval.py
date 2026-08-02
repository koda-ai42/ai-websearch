from benchmarks.stage5 import run_stage5_benchmark


def test_stage5_is_deterministic_and_separates_metric_families() -> None:
    first = run_stage5_benchmark()
    assert first == run_stage5_benchmark()
    for group in (
        "fts_policies",
        "vector_candidate_policies",
        "fusion_policies",
        "source_score_policies",
    ):
        for result in first[group].values():
            assert {"accuracy", "reliability", "latency"} <= result.keys()
    assert first["evaluation_protocol"]["reranker_used"] is False
    assert first["live_integrations_executed"] == []


def test_fts_errors_are_distinct_from_retrieval_quality() -> None:
    result = run_stage5_benchmark()["fts_policies"]
    assert result["raw_silent"]["reliability"]["operation_counts"]["silent_empty_failure"] == 2
    assert (
        result["raw_observable"]["reliability"]["operation_counts"]["observable_query_error"] == 2
    )
    assert result["raw_silent"]["accuracy"] == result["raw_observable"]["accuracy"]
    assert result["raw_silent"]["accuracy"]["retrieval_quality_applicable_cases"] == 3
    assert result["sanitized_and"]["accuracy"]["retrieval_quality_applicable_cases"] == 5
    failed = [case for case in result["raw_silent"]["cases"] if case["query_failed"]]
    assert all(case["precision"] is None and case["recall"] is None for case in failed)
    assert result["sanitized_and"]["reliability"]["query_failure_rate"] == 0.0


def test_vector_candidate_recall_scales_without_claiming_less_scan_work() -> None:
    policies = run_stage5_benchmark()["vector_candidate_policies"]
    recalls = [
        policies[f"candidate_k_{k}"]["accuracy"]["mean_candidate_recall"] for k in (4, 8, 16, 32)
    ]
    assert recalls == sorted(recalls)
    assert {policies[name]["reliability"]["vector_comparisons"] for name in policies} == {56}
    assert (
        policies["candidate_k_4"]["reliability"]["materialized_candidates"]
        < policies["candidate_k_32"]["reliability"]["materialized_candidates"]
    )


def test_fusion_and_source_score_are_one_factor_at_a_time() -> None:
    result = run_stage5_benchmark()
    original_fusion = result["fusion_policies"]["original_minmax_70_30"]
    original_source = result["source_score_policies"]["original_source_multiplier"]
    assert original_fusion == original_source
    assert all(
        not policy["reliability"]["reranker_used"] for policy in result["fusion_policies"].values()
    )
