from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from .metrics import duplicate_rate, ndcg, reciprocal_rank, safe_ratio

DEFAULT_CORPUS = Path(__file__).with_name("fixtures") / "stage9_v1" / "reranking_corpus.json"


def _rank(case: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    candidates = list(case["candidates"])
    if mode == "off":
        return candidates
    key = "heuristic_score" if mode == "heuristic" else "cross_encoder_score"
    return sorted(candidates, key=lambda item: (-float(item[key]), int(item["hybrid_rank"])))


def _evaluate(case: dict[str, Any], mode: str) -> dict[str, Any]:
    ranked = _rank(case, mode)
    selected = ranked[: case["selection_limit"]]
    relevant = set(case["relevant_ids"])
    return {
        "id": case["id"],
        "category": case["category"],
        "mrr": reciprocal_rank([item["id"] for item in ranked], relevant),
        "ndcg_at_10": ndcg([item["id"] for item in ranked[:10]], relevant),
        "relevant_chunk_ratio": safe_ratio(
            sum(item["id"] in relevant for item in selected), len(selected)
        ),
        "duplicate_chunk_ratio": duplicate_rate([item["text"] for item in selected]),
        "citation_support": float(any(item["id"] in relevant for item in selected)),
        "final_answer_correctness_proxy": float(
            relevant.issubset({item["id"] for item in selected})
        ),
        "reranking_latency_ms": 0.0
        if mode == "off"
        else (0.08 if mode == "heuristic" else 2.5) * min(len(ranked), 24),
        "total_latency_ms": 5.0
        + (0.0 if mode == "off" else (0.08 if mode == "heuristic" else 2.5) * min(len(ranked), 24)),
    }


def run_stage9_benchmark(corpus_path: Path | None = None) -> dict[str, Any]:
    corpus = json.loads((corpus_path or DEFAULT_CORPUS).read_text(encoding="utf-8"))
    modes = {}
    for mode in ("off", "heuristic", "cross_encoder"):
        rows = [_evaluate(case, mode) for case in corpus["cases"]]
        metrics = (
            "mrr",
            "ndcg_at_10",
            "relevant_chunk_ratio",
            "duplicate_chunk_ratio",
            "citation_support",
            "final_answer_correctness_proxy",
            "reranking_latency_ms",
            "total_latency_ms",
        )
        modes[mode] = {
            "overall": {metric: mean(float(row[metric]) for row in rows) for metric in metrics},
            "by_category": {
                category: {
                    metric: mean(float(row[metric]) for row in rows if row["category"] == category)
                    for metric in metrics
                }
                for category in sorted({row["category"] for row in rows})
            },
            "peak_memory_bytes": None,
            "cases": rows,
        }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_stage9_configurable_reranking_replay",
        "evaluation_protocol": {
            "same_questions_database_candidate_pool_extraction_embeddings_and_selection": True,
            "scores": "Frozen fake reranker scores; no model download, network, database, or live inference.",
            "latency": "Deterministic fixture cost model, not observed wall-clock latency.",
        },
        "modes": modes,
    }
