from benchmarks.request_deadlines import run_request_deadline_benchmark


def test_remaining_request_deadline_preserves_outcomes_and_bounds_work() -> None:
    result = run_request_deadline_benchmark()
    before = result["policies"]["operation_timeouts_only"]
    after = result["policies"]["remaining_request_deadline"]
    assert before["accuracy"]["outcome_accuracy"] == 0.5
    assert after["accuracy"]["outcome_accuracy"] == 1.0
    assert after["reliability"] == {
        "deadline_compliance": 1.0,
        "distinct_deadline_outcome": True,
    }
