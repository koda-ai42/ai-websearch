from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_websearch.access_outcomes import classify_access_outcome
from ai_websearch.models import ContextChunk
from ai_websearch.research_controller import assess_evidence
from ai_websearch.retrieval import _filter_for_reranking

DEFAULT_CORPUS = (
    Path(__file__).with_name("fixtures") / "stage12_v1" / "evidence_integrity_corpus.json"
)


def _materialize(item: dict[str, Any]) -> str:
    body = " ".join([str(item["seed"])] * int(item.get("repeat", 1)))
    suffix = str(item.get("suffix", "")).strip()
    return f"{body} {suffix}".strip()


def _chunk(item: dict[str, Any], chunk_id: int) -> ContextChunk:
    return ContextChunk(
        chunk_id=chunk_id,
        source_id=int(item["source_id"]),
        url=f"https://source-{item['source_id']}.test/article",
        title=str(item["title"]),
        fetched_at="2026-08-02T00:00:00Z",
        chunk_index=0,
        text=_materialize(item),
        score=1.0 / chunk_id,
        vector_rank=item.get("vector_rank"),
        keyword_rank=item.get("keyword_rank"),
        pre_rerank_rank=chunk_id,
    )


def run_stage12_benchmark(path: Path | None = None) -> dict[str, Any]:
    selected = (path or DEFAULT_CORPUS).resolve()
    corpus = json.loads(selected.read_text(encoding="utf-8"))

    crawl_rows: list[dict[str, Any]] = []
    wall_total = wall_rejected = 0
    legitimate_total = legitimate_accepted = 0
    for case in corpus["crawl_cases"]:
        expected = str(case["expected_outcome"])
        observed = classify_access_outcome(str(case["title"]), None, _materialize(case))
        is_wall = expected != "success"
        wall_total += int(is_wall)
        wall_rejected += int(is_wall and observed != "success")
        legitimate_total += int(not is_wall)
        legitimate_accepted += int(not is_wall and observed == "success")
        crawl_rows.append(
            {
                "id": case["id"],
                "expected": expected,
                "observed": observed,
                "correct": observed == expected,
            }
        )

    evidence_rows: list[dict[str, Any]] = []
    gate_correct = false_sufficient = retained_bad = retained_total = 0
    for case in corpus["evidence_cases"]:
        candidates = [_chunk(item, index) for index, item in enumerate(case["candidates"], 1)]
        usable = {
            candidate.chunk_id: bool(item["usable"])
            for candidate, item in zip(candidates, case["candidates"])
        }
        filtered, metadata = _filter_for_reranking(str(case["query"]), candidates, len(candidates))
        assessment = assess_evidence(str(case["query"]), filtered)
        expected = bool(case["expected_sufficient"])
        correct = assessment.sufficient == expected
        gate_correct += int(correct)
        false_sufficient += int(assessment.sufficient and not expected)
        retained_bad += sum(not usable[item.chunk_id] for item in filtered)
        retained_total += len(filtered)
        evidence_rows.append(
            {
                "id": case["id"],
                "expected_sufficient": expected,
                "observed_sufficient": assessment.sufficient,
                "reason": assessment.reason,
                "correct": correct,
                "candidates_before": len(candidates),
                "candidates_after": len(filtered),
                "bad_candidates_retained": sum(not usable[item.chunk_id] for item in filtered),
                "filter_rejections": metadata["filter_rejections"],
            }
        )

    crawl_correct = sum(row["correct"] for row in crawl_rows)
    return {
        "schema_version": "1.0",
        "corpus_version": corpus["version"],
        "run_mode": "offline_production_policy",
        "accuracy": {
            "crawl_outcome_accuracy": crawl_correct / len(crawl_rows),
            "wall_rejection_rate": wall_rejected / wall_total,
            "legitimate_acceptance_rate": legitimate_accepted / legitimate_total,
            "evidence_gate_accuracy": gate_correct / len(evidence_rows),
            "false_sufficient_count": false_sufficient,
            "retained_candidate_precision": (
                (retained_total - retained_bad) / retained_total if retained_total else 1.0
            ),
        },
        "reliability": {
            "consent_or_shell_cases_accepted": wall_total - wall_rejected,
            "known_bad_candidates_retained": retained_bad,
            "network_access": False,
            "browser_execution": False,
            "model_inference": False,
            "database_access": False,
        },
        "latency": {
            "measured": False,
            "crawl_cases_evaluated": len(crawl_rows),
            "evidence_cases_evaluated": len(evidence_rows),
        },
        "crawl_cases": crawl_rows,
        "evidence_cases": evidence_rows,
        "limitations": [
            "Synthetic text exercises production policy helpers without network or browser execution.",
            "No embedding or CrossEncoder inference is performed.",
            "Latency fields are deterministic case counts, not wall-clock measurements.",
        ],
    }
