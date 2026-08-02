from benchmarks.stage9 import run_stage9_benchmark


def test_stage9_compares_same_frozen_pool_in_all_modes() -> None:
    result = run_stage9_benchmark()
    assert set(result["modes"]) == {"off", "heuristic", "cross_encoder"}
    assert (
        result["evaluation_protocol"][
            "same_questions_database_candidate_pool_extraction_embeddings_and_selection"
        ]
        is True
    )
    assert (
        result["modes"]["cross_encoder"]["overall"]["mrr"]
        >= result["modes"]["off"]["overall"]["mrr"]
    )
    assert all(value["peak_memory_bytes"] is None for value in result["modes"].values())
