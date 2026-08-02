from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .metrics import mean, safe_ratio
from .trace import StageTracer

DEFAULT_STAGE6_CORPUS = Path(__file__).with_name("fixtures") / "stage6_v1" / "diversity_corpus.json"
POLICIES = (
    "score_order_baseline",
    "canonical_dedup",
    "source_dedup",
    "domain_dedup",
    "near_duplicate_penalty",
    "per_source_cap_2",
    "marginal_novelty",
)


def load_stage6_corpus(path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    selected = (path or DEFAULT_STAGE6_CORPUS).resolve()
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if payload.get("version") != "2026-07-15.stage6.v1":
        raise ValueError("unsupported Stage 6 corpus version")
    if not payload.get("cases"):
        raise ValueError("Stage 6 corpus requires cases")
    return selected, payload


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(left: str, right: str) -> float:
    left_words, right_words = _words(left), _words(right)
    return safe_ratio(len(left_words & right_words), len(left_words | right_words))


def _select(case: dict[str, Any], policy: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates = sorted(case["chunks"], key=lambda chunk: (-chunk["score"], chunk["id"]))
    selected: list[dict[str, Any]] = []
    operations: Counter[str] = Counter()
    while candidates and len(selected) < case["top_k"]:
        eligible = candidates
        if policy == "canonical_dedup":
            seen = {chunk["canonical_url"] for chunk in selected}
            eligible = [chunk for chunk in candidates if chunk["canonical_url"] not in seen]
        elif policy == "source_dedup":
            seen = {chunk["source_id"] for chunk in selected}
            eligible = [chunk for chunk in candidates if chunk["source_id"] not in seen]
        elif policy == "domain_dedup":
            seen = {chunk["domain"] for chunk in selected}
            eligible = [chunk for chunk in candidates if chunk["domain"] not in seen]
        elif policy == "per_source_cap_2":
            counts = Counter(chunk["source_id"] for chunk in selected)
            eligible = [chunk for chunk in candidates if counts[chunk["source_id"]] < 2]
        if not eligible:
            break
        if policy == "near_duplicate_penalty":
            seen_groups = {chunk["near_group"] for chunk in selected}
            chosen = min(
                eligible,
                key=lambda chunk: (
                    -chunk["score"] * (0.55 if chunk["near_group"] in seen_groups else 1.0),
                    -chunk["score"],
                    chunk["id"],
                ),
            )
            operations["near_duplicate_comparisons"] += len(eligible)
        elif policy == "marginal_novelty" and selected:

            def utility(chunk: dict[str, Any]) -> tuple[float, float, str]:
                similarity = max(_jaccard(chunk["text"], prior["text"]) for prior in selected)
                return (
                    -chunk["score"] * (0.65 + 0.35 * (1.0 - similarity)),
                    -chunk["score"],
                    chunk["id"],
                )

            chosen = min(eligible, key=utility)
            operations["novelty_comparisons"] += len(eligible) * len(selected)
        else:
            chosen = eligible[0]
        selected.append(chosen)
        candidates.remove(chosen)
        operations["candidates_selected"] += 1
    operations["selection_shortfall"] += int(len(selected) < case["top_k"])
    return selected, operations


def _evidence_metrics(
    selected: list[dict[str, Any]], relevant: set[str], cutoff: int
) -> dict[str, float]:
    seen: set[str] = set()
    gains: list[float] = []
    first_rank = 0
    for rank, chunk in enumerate(selected, start=1):
        evidence = chunk["evidence_id"]
        gain = float(evidence in relevant and evidence not in seen)
        gains.append(gain)
        if gain and not first_rank:
            first_rank = rank
        seen.add(evidence)
    ideal_count = min(len(relevant), cutoff)
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return {
        "evidence_precision": safe_ratio(sum(gains), len(selected)),
        "evidence_recall": safe_ratio(len(seen & relevant), len(relevant)),
        "reciprocal_rank": safe_ratio(1, first_rank),
        "ndcg": safe_ratio(dcg, ideal),
    }


def _run_policy(cases: list[dict[str, Any]], policy: str, baseline: dict[str, list[str]]) -> dict:
    rows = []
    operations: Counter[str] = Counter()
    tracer = StageTracer()
    for case in cases:
        selected, case_operations = _select(case, policy)
        operations.update(case_operations)
        selected_ids = [chunk["id"] for chunk in selected]
        relevant = set(case["relevant_evidence_ids"])
        accuracy = _evidence_metrics(selected, relevant, case["top_k"])
        strong = set(case["strong_corroborating_ids"])
        baseline_strong = strong & set(baseline[case["id"]])
        retained = baseline_strong & set(selected_ids)
        canonical_count = len({chunk["canonical_url"] for chunk in selected})
        source_count = len({chunk["source_id"] for chunk in selected})
        domain_count = len({chunk["domain"] for chunk in selected})
        near_count = len({chunk["near_group"] for chunk in selected})
        tracer.record(
            "diversity_selection",
            0.01 * len(case["chunks"]) + 0.002 * sum(case_operations.values()),
        )
        rows.append(
            {
                "id": case["id"],
                "selected_ids": selected_ids,
                **accuracy,
                "unique_canonical_urls": canonical_count,
                "unique_sources": source_count,
                "unique_domains": domain_count,
                "near_duplicate_rate": safe_ratio(len(selected) - near_count, len(selected)),
                "baseline_strong_corroborators": len(baseline_strong),
                "strong_corroborators_retained": len(retained),
                "strong_corroborators_displaced": len(baseline_strong - retained),
            }
        )
    return {
        "accuracy": {
            key: mean([row[key] for row in rows])
            for key in ("evidence_precision", "evidence_recall", "reciprocal_rank", "ndcg")
        },
        "diversity": {
            key: mean([float(row[key]) for row in rows])
            for key in (
                "unique_canonical_urls",
                "unique_sources",
                "unique_domains",
                "near_duplicate_rate",
            )
        },
        "corroboration": {
            "retention_rate": safe_ratio(
                sum(row["strong_corroborators_retained"] for row in rows),
                sum(row["baseline_strong_corroborators"] for row in rows),
            ),
            "displaced_count": sum(row["strong_corroborators_displaced"] for row in rows),
            "baseline_applicable_count": sum(row["baseline_strong_corroborators"] for row in rows),
        },
        "reliability": {
            "operation_counts": dict(sorted(operations.items())),
            "selection_shortfall_rate": mean(
                [
                    float(
                        len(row["selected_ids"])
                        < next(case["top_k"] for case in cases if case["id"] == row["id"])
                    )
                    for row in rows
                ]
            ),
        },
        "latency": tracer.summary(),
        "cases": rows,
    }


def run_stage6_benchmark(corpus_path: Path | None = None) -> dict:
    path, corpus = load_stage6_corpus(corpus_path)
    try:
        display_path = str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(path)
    baseline = {
        case["id"]: [chunk["id"] for chunk in _select(case, "score_order_baseline")[0]]
        for case in corpus["cases"]
    }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_stage6_diversity_policy_replay",
        "corpus": {"version": corpus["version"], "path": display_path},
        "evaluation_protocol": {
            "scope": "Independent synthetic canonical/source/domain deduplication, near-duplicate penalty, per-source cap, and marginal-novelty experiments.",
            "accuracy_credit": "Each relevant evidence identity receives credit at most once; aliases and near-duplicates cannot inflate accuracy.",
            "corroboration": "Retention is measured against explicitly labeled strong corroborators selected by score-order baseline.",
            "latency": "Deterministic fixture durations and operation counts, not live retrieval measurements.",
            "database_access": "No database is opened by Stage 6 replay.",
        },
        "policies": {policy: _run_policy(corpus["cases"], policy, baseline) for policy in POLICIES},
        "live_integrations_executed": [],
    }
