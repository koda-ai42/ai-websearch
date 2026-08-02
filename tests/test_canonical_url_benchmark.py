from benchmarks.canonical_urls import run_canonical_url_benchmark


def test_canonical_candidates_resolve_relative_urls_and_enforce_policy() -> None:
    result = run_canonical_url_benchmark()
    before = result["policies"]["unresolved_href"]
    after = result["policies"]["resolved_policy_checked"]
    assert before["accuracy"]["canonical_resolution_accuracy"] == 0.75
    assert after["accuracy"]["canonical_resolution_accuracy"] == 1.0
    assert after["reliability"] == {
        "relative_urls_resolved": True,
        "network_policy_required_before_storage": True,
    }
