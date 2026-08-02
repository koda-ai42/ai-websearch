from benchmarks.research_limits import run_research_limits_benchmark


def test_production_research_limits_match_recorded_policy() -> None:
    result = run_research_limits_benchmark()

    assert result["implementation"] == "mode_specific_request_limits"
    assert result["accuracy"]["mode_limit_policy_conformance"] == 1.0
    assert result["reliability"]["request_wide_page_bound_violations"] == 0
    assert result["reliability"]["progression_contract_violations"] == 0
    assert result["latency"]["synthetic_maximum_page_attempts_across_modes"] == 17
    assert result["progression"]["contract_conformance"] == 1.0
