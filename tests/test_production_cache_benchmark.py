from benchmarks.production_cache import run_production_cache_benchmark


def test_production_stale_fallback_benchmark() -> None:
    result = run_production_cache_benchmark()
    assert result["accuracy"] == {
        "stale_fallback_retrievable": True,
        "old_topic_still_retrievable": True,
        "refresh_outcome_recorded": True,
    }
    assert result["reliability"]["good_source_preserved"] is True
    assert result["reliability"]["active_versions"] == 1
    assert result["reliability"]["cache_status"] == "stale_fallback"
    assert result["reliability"]["network_access"] is False
