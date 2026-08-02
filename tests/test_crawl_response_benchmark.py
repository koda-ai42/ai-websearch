from benchmarks.crawl_responses import run_crawl_response_benchmark


def test_response_aware_crawl_policy_distinguishes_terminal_outcomes() -> None:
    result = run_crawl_response_benchmark()
    before = result["policies"]["content_only"]
    after = result["policies"]["response_aware"]
    assert after["accuracy"]["outcome_accuracy"] == 1.0
    assert after["accuracy"]["outcome_accuracy"] > before["accuracy"]["outcome_accuracy"]
    assert after["reliability"] == {
        "robots_distinct": True,
        "http_status_used": True,
        "empty_content_distinct": True,
    }
    assert result["retry_policy"] == {
        "timeout_retryable": True,
        "connection_retryable": True,
        "deterministic_value_error_retryable": False,
    }
