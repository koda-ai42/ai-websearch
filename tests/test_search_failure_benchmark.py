from benchmarks.search_failures import run_search_failure_benchmark


def test_search_failure_diagnostics_distinguish_all_outcomes() -> None:
    result = run_search_failure_benchmark()
    before = result["policies"]["silent_failures"]
    after = result["policies"]["diagnostic_failures"]
    assert before["accuracy"]["outcome_accuracy"] == 1 / 3
    assert after["accuracy"]["outcome_accuracy"] == 1.0
    assert after["reliability"] == {
        "partial_failure_observable": True,
        "total_failure_raises": True,
        "valid_empty_distinct": True,
    }
