from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .metrics import mean, ndcg, precision_recall, reciprocal_rank
from .trace import StageTracer

DEFAULT_STAGE5_CORPUS = Path(__file__).with_name("fixtures") / "stage5_v1" / "retrieval_corpus.json"
STOPWORDS = {"a", "an", "and", "for", "is", "of", "or", "the", "to", "what"}


def load_stage5_corpus(path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    selected = (path or DEFAULT_STAGE5_CORPUS).resolve()
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if payload.get("version") != "2026-07-15.stage5.v1":
        raise ValueError("unsupported Stage 5 corpus version")
    for section in ("fts_cases", "vector_cases", "ranking_cases"):
        if not payload.get(section):
            raise ValueError(f"Stage 5 corpus requires {section}")
    return selected, payload


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _fts_query(case: dict[str, Any], policy: str) -> tuple[list[str], str, bool]:
    query = case["query"].replace('"', "")
    raw_error = bool(re.search(r"[:?]", query) or "near(" in query.lower())
    if policy.startswith("raw_"):
        return _tokens(query), "raw", raw_error
    return (
        [term for term in _tokens(query) if term not in STOPWORDS],
        "or" if policy.endswith("_or") else "and",
        False,
    )


def _run_fts(cases: list[dict[str, Any]], policy: str) -> dict:
    rows = []
    operations: Counter[str] = Counter()
    tracer = StageTracer()
    for case in cases:
        terms, mode, failed = _fts_query(case, policy)
        observable = failed and policy != "raw_silent"
        returned: list[str] = []
        if not failed:
            for document in case["documents"]:
                words = set(_tokens(document["text"]))
                matched = (
                    any(term in words for term in terms)
                    if mode == "or"
                    else all(term in words for term in terms)
                )
                if matched:
                    returned.append(document["id"])
        operations["fts_query"] += 1
        operations["fts_query_failure"] += int(failed)
        operations["observable_query_error"] += int(observable)
        operations["silent_empty_failure"] += int(failed and not observable)
        tracer.record("fts", 0.03 + 0.005 * len(case["documents"]), not failed)
        relevant = set(case["relevant_ids"])
        precision, recall = precision_recall(returned, relevant) if not failed else (None, None)
        rows.append(
            {
                "id": case["id"],
                "returned_ids": returned,
                "precision": precision,
                "recall": recall,
                "reciprocal_rank": reciprocal_rank(returned, relevant) if not failed else None,
                "ndcg": ndcg(returned, relevant) if not failed else None,
                "query_failed": failed,
                "error_observable": observable,
            }
        )
    successful = [row for row in rows if not row["query_failed"]]
    return {
        "accuracy": {
            **{
                key: mean([row[key] for row in successful])
                for key in ("precision", "recall", "reciprocal_rank", "ndcg")
            },
            "retrieval_quality_applicable_cases": len(successful),
        },
        "reliability": {
            "operation_counts": dict(sorted(operations.items())),
            "query_failure_rate": mean([float(row["query_failed"]) for row in rows]),
            "silent_failure_rate": mean(
                [float(row["query_failed"] and not row["error_observable"]) for row in rows]
            ),
        },
        "latency": tracer.summary(),
        "cases": rows,
    }


def _run_vector(cases: list[dict[str, Any]], candidate_k: int) -> dict:
    tracer = StageTracer()
    rows = []
    comparisons = materialized = 0
    for case in cases:
        ranked = case["ranked_ids"]
        selected = ranked[:candidate_k]
        relevant = set(case["relevant_ids"])
        _, recall = precision_recall(selected, relevant)
        comparisons += len(ranked)
        materialized += len(selected)
        tracer.record("vector_scan", 0.01 * len(ranked) + 0.002 * len(selected))
        rows.append(
            {
                "id": case["id"],
                "corpus_size": len(ranked),
                "candidate_count": len(selected),
                "candidate_recall": recall,
            }
        )
    return {
        "accuracy": {"mean_candidate_recall": mean([row["candidate_recall"] for row in rows])},
        "reliability": {"vector_comparisons": comparisons, "materialized_candidates": materialized},
        "latency": tracer.summary(),
        "cases": rows,
    }


def _minmax(values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    return (
        [1.0] * len(values) if high == low else [(value - low) / (high - low) for value in values]
    )


def _rank_scores(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (-values[index], index))
    scores = [0.0] * len(values)
    denominator = max(1, len(values) - 1)
    for rank, index in enumerate(order):
        scores[index] = 1.0 - rank / denominator
    return scores


def _source_multiplier(score: float, policy: str) -> float:
    if policy == "no_source_multiplier":
        return 1.0
    if policy == "strong_source_multiplier":
        return 0.5 + 0.5 * max(0.0, min(1.0, score))
    return 0.85 + 0.15 * max(0.0, min(1.0, score))


def _rank_case(case: dict[str, Any], fusion: str, source_policy: str) -> list[str]:
    chunks = case["chunks"]
    vector_values = [chunk["vector"] for chunk in chunks]
    keyword_values = [chunk["keyword"] for chunk in chunks]
    if fusion == "rank_calibrated_70_30":
        vector, keyword = _rank_scores(vector_values), _rank_scores(keyword_values)
        scores = [0.7 * vector[i] + 0.3 * keyword[i] for i in range(len(chunks))]
    elif fusion == "minmax_50_50":
        vector, keyword = _minmax(vector_values), _minmax(keyword_values)
        scores = [0.5 * vector[i] + 0.5 * keyword[i] for i in range(len(chunks))]
    elif fusion == "weighted_rrf_70_30":
        vr, kr = _rank_scores(vector_values), _rank_scores(keyword_values)
        scores = [
            0.7 / (60 + (len(chunks) - vr[i] * max(1, len(chunks) - 1)))
            + 0.3 / (60 + (len(chunks) - kr[i] * max(1, len(chunks) - 1)))
            for i in range(len(chunks))
        ]
    else:
        vector, keyword = _minmax(vector_values), _minmax(keyword_values)
        scores = [0.7 * vector[i] + 0.3 * keyword[i] for i in range(len(chunks))]
    scored = [
        (scores[i] * _source_multiplier(chunk["source"], source_policy), i, chunk["id"])
        for i, chunk in enumerate(chunks)
    ]
    return [
        item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1]))[: case["top_k"]]
    ]


def _run_ranking(cases: list[dict[str, Any]], fusion: str, source_policy: str) -> dict:
    tracer = StageTracer()
    rows = []
    for case in cases:
        ranked = _rank_case(case, fusion, source_policy)
        relevant = set(case["relevant_ids"])
        precision, recall = precision_recall(ranked, relevant)
        tracer.record("normalization_fusion", 0.01 * len(case["chunks"]))
        rows.append(
            {
                "id": case["id"],
                "ranked_ids": ranked,
                "precision": precision,
                "recall": recall,
                "reciprocal_rank": reciprocal_rank(ranked, relevant),
                "ndcg": ndcg(ranked, relevant),
            }
        )
    return {
        "accuracy": {
            key: mean([row[key] for row in rows])
            for key in ("precision", "recall", "reciprocal_rank", "ndcg")
        },
        "reliability": {"cases_evaluated": len(rows), "reranker_used": False},
        "latency": tracer.summary(),
        "cases": rows,
    }


def run_stage5_benchmark(corpus_path: Path | None = None) -> dict:
    path, corpus = load_stage5_corpus(corpus_path)
    try:
        display_path = str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(path)
    fusion_policies = (
        "original_minmax_70_30",
        "rank_calibrated_70_30",
        "minmax_50_50",
        "weighted_rrf_70_30",
    )
    source_policies = (
        "original_source_multiplier",
        "no_source_multiplier",
        "strong_source_multiplier",
    )
    return {
        "schema_version": "1.0",
        "run_mode": "offline_stage5_retrieval_policy_replay",
        "corpus": {"version": corpus["version"], "path": display_path},
        "evaluation_protocol": {
            "scope": "Independent synthetic FTS, vector-candidate, fusion, and source-score experiments.",
            "latency": "Deterministic fixture durations and operation counts, not live retrieval measurements.",
            "database_access": "No SQLite or production database is opened.",
            "one_factor_at_a_time": True,
            "reranker_used": False,
        },
        "fts_policies": {
            name: _run_fts(corpus["fts_cases"], name)
            for name in ("raw_silent", "raw_observable", "sanitized_and", "sanitized_or")
        },
        "vector_candidate_policies": {
            f"candidate_k_{k}": _run_vector(corpus["vector_cases"], k) for k in (4, 8, 16, 32)
        },
        "fusion_policies": {
            name: _run_ranking(corpus["ranking_cases"], name, "original_source_multiplier")
            for name in fusion_policies
        },
        "source_score_policies": {
            name: _run_ranking(corpus["ranking_cases"], "original_minmax_70_30", name)
            for name in source_policies
        },
        "live_integrations_executed": [],
    }
