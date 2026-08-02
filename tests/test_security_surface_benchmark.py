from benchmarks.security_surface import run_security_surface_benchmark


def test_publication_security_policy_covers_each_release_control() -> None:
    result = run_security_surface_benchmark()
    before = result["policies"]["existing_surface"]["reliability"]
    after = result["policies"]["publication_hardened"]["reliability"]
    assert before == {
        "controls_passed": 0,
        "controls_total": 8,
        "control_coverage": 0.0,
    }
    assert after == {
        "controls_passed": 8,
        "controls_total": 8,
        "control_coverage": 1.0,
    }
