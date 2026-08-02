from benchmarks.evidence_representation import run_evidence_representation_benchmark


def test_clean_evidence_representation_removes_indexed_boilerplate() -> None:
    result = run_evidence_representation_benchmark()
    before = result["policies"]["stored_security_prefix"]
    after = result["policies"]["clean_storage_rendered_boundary"]
    assert after["accuracy"]["evidence_token_share"] == 1.0
    assert after["accuracy"]["evidence_token_share"] > before["accuracy"]["evidence_token_share"]
    assert before["accuracy"]["security_boilerplate_tokens_per_chunk"] > 0
    assert after["accuracy"]["security_boilerplate_tokens_per_chunk"] == 0
    assert after["reliability"]["untrusted_boundary_rendered"] is True
    assert after["reliability"]["requires_database_rebuild"] is True
