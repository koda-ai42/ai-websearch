from benchmarks.freshness_metadata import run_freshness_metadata_benchmark


def test_freshness_metadata_policy_improves_provenance() -> None:
    result = run_freshness_metadata_benchmark()
    before = result["policies"]["meta_time_year"]
    after = result["policies"]["provenance_aware"]
    assert after["accuracy"] == {
        "date_provenance_accuracy": 1.0,
    }
    assert (
        after["accuracy"]["date_provenance_accuracy"]
        > before["accuracy"]["date_provenance_accuracy"]
    )
    assert after["reliability"] == {
        "future_dates_rejected": True,
        "search_hints_distinguishable": True,
    }
