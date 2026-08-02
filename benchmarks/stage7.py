from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metrics import mean, safe_ratio
from .trace import StageTracer

DEFAULT_STAGE7_CORPUS = Path(__file__).with_name("fixtures") / "stage7_v1" / "context_corpus.json"


@dataclass(frozen=True)
class PackingPolicy:
    name: str
    max_chunks: int
    max_sources: int
    per_source: int
    char_budget: int | None = None
    relevance_floor: float | None = None
    marginal_gain: bool = False
    explicit_relations: bool = False


POLICIES = {
    policy.name: policy
    for policy in (
        PackingPolicy("phase1_eight_12000_chars", 8, 1000, 2, char_budget=12000),
        PackingPolicy("current_balanced_25", 25, 10, 3),
        PackingPolicy("relevance_floor_0_65", 25, 10, 3, relevance_floor=0.65),
        PackingPolicy("marginal_evidence_gain", 25, 10, 3, marginal_gain=True),
        PackingPolicy("explicit_conflict_corroboration", 25, 10, 3, explicit_relations=True),
        PackingPolicy("balanced_cap_6", 6, 10, 3),
        PackingPolicy("balanced_cap_8", 8, 10, 3),
        PackingPolicy("balanced_cap_10", 10, 10, 3),
        PackingPolicy(
            "combined_candidate_cap_6",
            6,
            10,
            3,
            relevance_floor=0.65,
            marginal_gain=True,
            explicit_relations=True,
        ),
    )
}


def load_stage7_corpus(path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    selected = (path or DEFAULT_STAGE7_CORPUS).resolve()
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if payload.get("version") != "2026-07-15.stage7.v1":
        raise ValueError("unsupported Stage 7 corpus version")
    if not payload.get("cases"):
        raise ValueError("Stage 7 corpus requires cases")
    if not payload.get("render_accounting"):
        raise ValueError("Stage 7 corpus requires render_accounting")
    return selected, payload


def _expanded_chunks(case: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = [dict(chunk) for chunk in case["chunks"]]
    tail = case.get("noise_tail")
    if tail:
        for index in range(tail["count"]):
            chunks.append(
                {
                    "id": f"{case['id']}-noise-{index + 1:02d}",
                    "score": tail["score_start"] - index * tail["score_step"],
                    "source_id": f"noise-{index % tail['source_cycle'] + 1}",
                    "evidence_id": None,
                    "stance_group": None,
                    "stance": None,
                    "corroboration_group": None,
                    "tokens": tail["tokens"],
                    "chars": tail["chars"],
                }
            )
    return sorted(chunks, key=lambda chunk: (-chunk["score"], chunk["id"]))


def _relation_order(chunks: list[dict[str, Any]], case: dict[str, Any]) -> list[dict[str, Any]]:
    if not chunks:
        return []
    anchor = chunks[0]
    conflict_ids = set(case["conflict_chunk_ids"])
    corroborating_ids = set(case["corroborating_chunk_ids"])
    conflicts = [
        chunk for chunk in chunks if chunk["id"] in conflict_ids and chunk["id"] != anchor["id"]
    ]
    corroborators = [
        chunk
        for chunk in chunks
        if chunk["id"] in corroborating_ids and chunk["id"] != anchor["id"]
    ]
    used = {anchor["id"]} | conflict_ids | corroborating_ids
    remainder = [chunk for chunk in chunks if chunk["id"] not in used]
    return [anchor] + conflicts + corroborators + remainder


def _effective_limits(case: dict[str, Any], policy: PackingPolicy) -> tuple[int, int]:
    if policy.char_budget is not None:
        return policy.max_chunks, policy.max_sources
    budget_chunks = max(4, case["token_budget"] // 700)
    max_chunks = min(25, budget_chunks, policy.max_chunks)
    budget_sources = max(2, (max_chunks + 2) // 3)
    return max_chunks, min(10, budget_sources, policy.max_sources)


def _pack(
    case: dict[str, Any], policy: PackingPolicy
) -> tuple[list[dict[str, Any]], Counter[str], int, int]:
    chunks = _expanded_chunks(case)
    if policy.explicit_relations:
        chunks = _relation_order(chunks, case)
    selected: list[dict[str, Any]] = []
    operations: Counter[str] = Counter()
    per_source: Counter[str] = Counter()
    sources: set[str] = set()
    evidence_seen: set[str] = set()
    max_chunks, max_sources = _effective_limits(case, policy)
    tokens = case["payload_fixed_tokens"]
    chars = (
        case["phase1_fixed_chars"]
        if policy.char_budget is not None
        else case["payload_fixed_chars"]
    )
    required_ids = set(case["conflict_chunk_ids"]) | set(case["corroborating_chunk_ids"])
    for chunk in chunks:
        operations["candidate_checks"] += 1
        if (
            policy.relevance_floor is not None
            and chunk["score"] < policy.relevance_floor
            and chunk["id"] not in required_ids
        ):
            operations["below_relevance_floor"] += 1
            continue
        evidence = chunk["evidence_id"]
        gain = bool(evidence and evidence not in evidence_seen) or chunk["id"] in required_ids
        if policy.marginal_gain and not gain:
            operations["no_marginal_gain"] += 1
            continue
        source = chunk["source_id"]
        if per_source[source] >= policy.per_source or (
            source not in sources and len(sources) >= max_sources
        ):
            operations["source_limit_rejections"] += 1
            continue
        body_chars = chunk["chars"]
        body_tokens = chunk["tokens"]
        chunk_chars = (
            case["phase1_chunk_overhead_chars"]
            if policy.char_budget is not None
            else case["payload_chunk_overhead_chars"]
        )
        chunk_tokens = case["payload_chunk_overhead_tokens"]
        truncated = False
        if policy.char_budget is not None and chars + chunk_chars + body_chars > policy.char_budget:
            remaining = policy.char_budget - chars - chunk_chars
            if remaining <= 0:
                break
            body_chars = remaining
            body_tokens = min(body_tokens, math.ceil(chunk["tokens"] * remaining / chunk["chars"]))
            truncated = True
        if tokens + chunk_tokens + body_tokens > case["token_budget"]:
            if selected:
                operations["token_ceiling_rejections"] += 1
                break
            remaining_tokens = case["token_budget"] - tokens - chunk_tokens
            if remaining_tokens <= 0:
                operations["token_ceiling_rejections"] += 1
                break
            body_chars = min(
                body_chars, math.floor(chunk["chars"] * remaining_tokens / chunk["tokens"])
            )
            body_tokens = remaining_tokens
            truncated = True
        packed_chars = chunk_chars + body_chars
        packed_tokens = chunk_tokens + body_tokens
        chosen = {
            **chunk,
            "packed_chars": packed_chars,
            "packed_tokens": packed_tokens,
            "truncated": truncated,
        }
        selected.append(chosen)
        tokens += packed_tokens
        chars += packed_chars
        sources.add(source)
        per_source[source] += 1
        if evidence:
            evidence_seen.add(evidence)
        operations["chunks_packed"] += 1
        operations["truncated_chunks"] += int(truncated)
        if len(selected) >= max_chunks or truncated:
            break
    return selected, operations, tokens, chars


def _run_policy(cases: list[dict[str, Any]], policy: PackingPolicy) -> dict:
    rows = []
    operations: Counter[str] = Counter()
    tracer = StageTracer()
    for case in cases:
        selected, case_operations, tokens, chars = _pack(case, policy)
        effective_max_chunks, effective_max_sources = _effective_limits(case, policy)
        operations.update(case_operations)
        ids = {chunk["id"] for chunk in selected}
        evidence = {chunk["evidence_id"] for chunk in selected if chunk["evidence_id"]}
        relevant = set(case["relevant_evidence_ids"])
        answer_applicable = bool(relevant)
        conflict_expected = set(case["conflict_chunk_ids"])
        corroboration_expected = set(case["corroborating_chunk_ids"])
        precision = (
            safe_ratio(sum(chunk["evidence_id"] in relevant for chunk in selected), len(selected))
            if answer_applicable
            else None
        )
        recall = safe_ratio(len(evidence & relevant), len(relevant)) if answer_applicable else None
        readiness = relevant <= evidence and conflict_expected <= ids if answer_applicable else None
        conflict_coverage = (
            safe_ratio(len(conflict_expected & ids), len(conflict_expected))
            if conflict_expected
            else None
        )
        corroboration_coverage = (
            safe_ratio(len(corroboration_expected & ids), len(corroboration_expected))
            if corroboration_expected
            else None
        )
        abstention = not selected if not answer_applicable else None
        tracer.record("rendering", 0.01 * len(selected) + 0.0005 * chars)
        rows.append(
            {
                "id": case["id"],
                "selected_ids": [chunk["id"] for chunk in selected],
                "chunks_packed": len(selected),
                "tokens_packed": tokens,
                "characters_packed": chars,
                "effective_max_chunks": effective_max_chunks,
                "effective_max_sources": effective_max_sources,
                "unused_token_budget": case["token_budget"] - tokens,
                "answer_chunk_precision": precision,
                "answer_evidence_recall": recall,
                "answer_readiness": readiness,
                "conflict_coverage": conflict_coverage,
                "corroboration_coverage": corroboration_coverage,
                "abstention_success": abstention,
                "token_budget_respected": tokens <= case["token_budget"],
                "truncated_chunks": sum(chunk["truncated"] for chunk in selected),
            }
        )

    def applicable(field: str) -> list[float]:
        return [float(row[field]) for row in rows if row[field] is not None]

    accuracy: dict[str, float | int] = {}
    for field in (
        "answer_chunk_precision",
        "answer_evidence_recall",
        "answer_readiness",
        "conflict_coverage",
        "corroboration_coverage",
        "abstention_success",
    ):
        values = applicable(field)
        accuracy[field] = mean(values)
        accuracy[f"{field}_applicable_cases"] = len(values)
    return {
        "accuracy": accuracy,
        "packing": {
            "mean_chunks_packed": mean([float(row["chunks_packed"]) for row in rows]),
            "mean_tokens_packed": mean([float(row["tokens_packed"]) for row in rows]),
            "mean_characters_packed": mean([float(row["characters_packed"]) for row in rows]),
            "mean_unused_token_budget": mean([float(row["unused_token_budget"]) for row in rows]),
        },
        "reliability": {
            "operation_counts": dict(sorted(operations.items())),
            "token_budget_violations": sum(not row["token_budget_respected"] for row in rows),
            "fixture_exact_token_counts": True,
            "live_llama_tokenize_executed": False,
        },
        "latency": tracer.summary(),
        "cases": rows,
    }


def run_stage7_benchmark(corpus_path: Path | None = None) -> dict:
    path, corpus = load_stage7_corpus(corpus_path)
    try:
        display_path = str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(path)
    cases = [{**corpus["render_accounting"], **case} for case in corpus["cases"]]
    policies = {name: _run_policy(cases, policy) for name, policy in POLICIES.items()}
    cap_values = (6, 8, 10)
    best_cap_recall = max(
        policies[f"balanced_cap_{cap}"]["accuracy"]["answer_evidence_recall"] for cap in cap_values
    )
    derived_cap = min(
        cap
        for cap in cap_values
        if math.isclose(
            policies[f"balanced_cap_{cap}"]["accuracy"]["answer_evidence_recall"], best_cap_recall
        )
    )
    return {
        "schema_version": "1.0",
        "run_mode": "offline_stage7_context_packing_replay",
        "corpus": {"version": corpus["version"], "path": display_path},
        "evaluation_protocol": {
            "scope": "Synthetic balanced context selection and packing policy comparison only.",
            "token_counts": "Frozen full-payload and per-chunk rendering annotations model exact counts; llama.cpp /tokenize is not called.",
            "budget_role": "The token budget is a hard safety ceiling; unused budget is descriptive and never an accuracy reward or failure.",
            "phase1_model": "Eight chunks, two per source, and a 12,000-character ceiling charged for fixed context, headers, and evidence bodies.",
            "current_model": "Balanced limits derived from applied_web_tokens using production chunk/source formulas, capped at 25 chunks and 10 sources, with full-payload token accounting.",
            "latency": "Deterministic fixture durations and operation counts, not live packing measurements.",
            "database_access": "No database is opened by Stage 7 replay.",
        },
        "cap_analysis": {
            "evaluated_caps": list(cap_values),
            "selection_rule": "Smallest evaluated cap matching the highest mean answer-evidence recall among cap-only policies.",
            "best_cap_policy_recall": best_cap_recall,
            "fixture_derived_balanced_cap": derived_cap,
            "production_decision": False,
        },
        "policies": policies,
        "live_integrations_executed": [],
    }
