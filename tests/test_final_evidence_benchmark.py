from benchmarks.final_evidence import run_final_evidence_benchmark


def test_final_evidence_reassessment_removes_false_answerable_results() -> None:
    result = run_final_evidence_benchmark()
    before = result["policies"]["pre_pack_only"]
    after = result["policies"]["final_pack_reassessment"]
    assert before["accuracy"] == {
        "answerability_accuracy": 0.5,
        "false_answerable_count": 2,
    }
    assert after["accuracy"] == {
        "answerability_accuracy": 1.0,
        "false_answerable_count": 0,
    }
    assert after["reliability"]["final_selection_assessed"] is True
