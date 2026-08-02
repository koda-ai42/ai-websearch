from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metrics import mean, ndcg, reciprocal_rank, safe_ratio, unique_domains
from .search_policies import POLICIES, SearchPolicy, merge_results, plan_queries
from .trace import StageTracer

DEFAULT_STAGE2_CORPUS = Path(__file__).with_name("fixtures") / "stage2_v1" / "search_corpus.json"


def load_stage2_corpus(path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    selected = (path or DEFAULT_STAGE2_CORPUS).resolve()
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if payload.get("version") != "2026-07-14.stage2.v1":
        raise ValueError("unsupported Stage 2 corpus version")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Stage 2 corpus requires cases")
    return selected, payload


def _run_case(case: dict[str, Any], policy: SearchPolicy, tracer: StageTracer) -> tuple[dict, int]:
    queries = plan_queries(case, policy)
    tracer.record("query_planning", 0.05)
    result_sets: list[list[dict[str, Any]]] = []
    failures = 0
    for query in queries:
        response = case["search"].get(query)
        ok = isinstance(response, list)
        tracer.record("search_request", float(case.get("search_duration_ms", 4.0)), ok)
        if not ok:
            failures += 1
            continue
        result_sets.append(response)
    ranked = merge_results(result_sets, policy)
    tracer.record("search_merge_dedup", 0.1 if policy.merger == "rrf" else 0.08)
    urls = [str(item.get("canonical_url") or item["url"]) for item in ranked]
    relevant = set(case.get("relevant_canonical_urls", []))
    unique_hits = len(set(urls) & relevant)
    precision = safe_ratio(unique_hits, len(urls))
    recall = safe_ratio(unique_hits, len(relevant))
    seen: set[str] = set()
    relevance_rank: list[str] = []
    for index, url in enumerate(urls):
        relevance_rank.append(url if url not in seen else f"__duplicate_{index}")
        seen.add(url)
    canonical_duplicates = len(urls) - len(set(urls))
    return {
        "id": case["id"],
        "category": case["category"],
        "queries": queries,
        "ranked_canonical_urls": urls,
        "search_precision": precision,
        "search_recall": recall,
        "mrr": reciprocal_rank(relevance_rank, relevant),
        "ndcg": ndcg(relevance_rank, relevant),
        "unique_canonical_sources": len(set(urls)),
        "unique_domains": unique_domains(urls),
        "canonical_duplicate_rate": safe_ratio(canonical_duplicates, len(urls)),
    }, failures


def _run_policy(cases: list[dict[str, Any]], policy: SearchPolicy) -> dict:
    tracer = StageTracer()
    results: list[dict] = []
    failed_queries = 0
    total_queries = 0
    zero_result_cases = 0
    for case in cases:
        before = len(tracer.events)
        result, failures = _run_case(case, policy, tracer)
        results.append(result)
        failed_queries += failures
        total_queries += len(result["queries"])
        zero_result_cases += not result["ranked_canonical_urls"]
        tracer.record("total", sum(event.duration_ms for event in tracer.events[before:]))
    metric_names = (
        "search_precision",
        "search_recall",
        "mrr",
        "ndcg",
        "unique_canonical_sources",
        "unique_domains",
        "canonical_duplicate_rate",
    )
    return {
        "accuracy": {name: mean([float(case[name]) for case in results]) for name in metric_names},
        "reliability": {
            "planned_queries": total_queries,
            "failed_queries": failed_queries,
            "query_failure_rate": safe_ratio(failed_queries, total_queries),
            "zero_result_case_rate": safe_ratio(zero_result_cases, len(cases)),
        },
        "latency": tracer.summary(),
        "cases": results,
    }


def run_stage2_benchmark(corpus_path: Path | None = None) -> dict:
    path, corpus = load_stage2_corpus(corpus_path)
    try:
        display_path = str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(path)
    return {
        "schema_version": "1.0",
        "run_mode": "offline_stage2_search_policy_replay",
        "corpus": {"version": corpus["version"], "path": display_path},
        "evaluation_protocol": {
            "scope": "Search planning and result merging only; no crawl or downstream retrieval execution.",
            "latency": "Deterministic fixture durations and operation counts, not live wall-clock measurements.",
            "peak_rss_bytes": "Not measured during offline replay; reported as null.",
        },
        "policies": {
            name: _run_policy(corpus["cases"], policy) for name, policy in POLICIES.items()
        },
        "live_integrations_executed": [],
    }
