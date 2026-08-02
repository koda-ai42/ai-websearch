from __future__ import annotations

from pathlib import Path

from ai_websearch.models import ContextChunk
from ai_websearch.research_controller import assess_evidence


def _chunk(identifier: int, text: str) -> ContextChunk:
    return ContextChunk(
        chunk_id=identifier,
        source_id=identifier,
        url=f"https://final-evidence-{identifier}.test/article",
        title="Relevant evidence",
        fetched_at="2026-08-02T00:00:00Z",
        chunk_index=0,
        text=text,
        score=1.0 / identifier,
        vector_rank=identifier,
        keyword_rank=identifier,
    )


def run_final_evidence_benchmark(_path: Path | None = None) -> dict:
    cases = [
        {
            "id": "complex-source-trim",
            "query": "Compare alpha versus beta and evaluate trade-offs",
            "candidates": [
                _chunk(1, "Alpha and beta have measured performance trade-offs."),
                _chunk(2, "Independent testing compares alpha and beta reliability trade-offs."),
            ],
            "selected": [_chunk(1, "Alpha and beta have measured performance trade-offs.")],
            "expected": False,
        },
        {
            "id": "simple-evidence-retained",
            "query": "What material does the prototype use?",
            "candidates": [_chunk(3, "The prototype uses recycled aluminium material.")],
            "selected": [_chunk(3, "The prototype uses recycled aluminium material.")],
            "expected": True,
        },
        {
            "id": "all-evidence-removed",
            "query": "What is the launch date?",
            "candidates": [_chunk(4, "The launch date is 12 October.")],
            "selected": [],
            "expected": False,
        },
        {
            "id": "diverse-comparison-retained",
            "query": "Compare red versus blue and evaluate trade-offs",
            "candidates": [
                _chunk(5, "Red and blue have measured cost trade-offs."),
                _chunk(6, "Independent evidence compares red and blue reliability trade-offs."),
            ],
            "selected": [
                _chunk(5, "Red and blue have measured cost trade-offs."),
                _chunk(6, "Independent evidence compares red and blue reliability trade-offs."),
            ],
            "expected": True,
        },
    ]

    def evaluate(use_final_selection: bool) -> dict:
        rows = []
        for case in cases:
            assessed = case["selected"] if use_final_selection else case["candidates"]
            observed = assess_evidence(case["query"], assessed).sufficient
            rows.append(
                {
                    "id": case["id"],
                    "expected_answerable": case["expected"],
                    "observed_answerable": observed,
                    "correct": observed == case["expected"],
                }
            )
        return {
            "accuracy": {
                "answerability_accuracy": sum(row["correct"] for row in rows) / len(rows),
                "false_answerable_count": sum(
                    row["observed_answerable"] and not row["expected_answerable"] for row in rows
                ),
            },
            "reliability": {"final_selection_assessed": use_final_selection},
            "cases": rows,
        }

    return {
        "schema_version": "1.0",
        "run_mode": "offline_final_evidence_policy",
        "policies": {
            "pre_pack_only": evaluate(False),
            "final_pack_reassessment": evaluate(True),
        },
        "latency": {"measured": False, "cases_evaluated": len(cases)},
        "limitations": [
            "Selection is frozen and deterministic; llama.cpp tokenization is not executed.",
            "Answerability is the production evidence-gate decision, not an LLM answer score.",
        ],
    }
