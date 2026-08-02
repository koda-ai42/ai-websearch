from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SearchPolicy:
    name: str
    planner: str
    merger: str = "raw_score"
    canonical_dedup: bool = False
    per_domain_limit: int | None = None


POLICIES = {
    policy.name: policy
    for policy in (
        SearchPolicy("original_only", "original"),
        SearchPolicy("existing_suffix_expansion", "existing"),
        SearchPolicy("query_type_aware_expansion", "query_type"),
        SearchPolicy("per_query_rrf", "existing", merger="rrf"),
        SearchPolicy("canonical_dedup", "existing", canonical_dedup=True),
        SearchPolicy(
            "canonical_dedup_domain_cap", "existing", canonical_dedup=True, per_domain_limit=2
        ),
    )
}


def plan_queries(case: dict[str, Any], policy: SearchPolicy) -> list[str]:
    query = str(case["query"]).strip()
    if policy.planner == "original":
        return [query]
    if policy.planner == "existing":
        return [query, f"{query} official source", f"{query} technical documentation"]
    category = case["category"]
    variants = {
        "technical_documentation": [
            query,
            f"{query} technical documentation",
            f"{query} official source",
        ],
        "current_events": [query, f"{query} latest", f"{query} official source"],
        "comparative_consumer": [query, f"{query} independent analysis"],
        "multi_hop": [query, f"{query} primary source"],
        "conflicting_sources": [query, f"{query} official source"],
    }
    return list(dict.fromkeys(variants.get(category, [query])))


def _identity(item: dict[str, Any], canonical: bool) -> str:
    if canonical:
        return str(item.get("canonical_url") or item["url"])
    return str(item["url"])


def _raw_merge(result_sets: list[list[dict[str, Any]]], canonical: bool) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for results in result_sets:
        for item in results:
            key = _identity(item, canonical)
            previous = deduped.get(key)
            if previous is None or (item.get("source_score", 0.5), item.get("score", 0.0)) > (
                previous.get("source_score", 0.5),
                previous.get("score", 0.0),
            ):
                deduped[key] = dict(item)
    return sorted(
        deduped.values(),
        key=lambda item: (
            float(item.get("source_score", 0.5)),
            float(item.get("score", 0.0)),
            item["url"],
        ),
        reverse=True,
    )


def _rrf_merge(
    result_sets: list[list[dict[str, Any]]], canonical: bool, constant: int = 60
) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for results in result_sets:
        for rank, item in enumerate(results, start=1):
            key = _identity(item, canonical)
            entry = fused.setdefault(key, {**item, "rrf_score": 0.0})
            entry["rrf_score"] += 1.0 / (constant + rank)
            if float(item.get("source_score", 0.5)) > float(entry.get("source_score", 0.5)):
                entry.update(item)
    return sorted(
        fused.values(),
        key=lambda item: (
            float(item["rrf_score"]),
            float(item.get("source_score", 0.5)),
            item["url"],
        ),
        reverse=True,
    )


def merge_results(
    result_sets: list[list[dict[str, Any]]], policy: SearchPolicy, limit: int = 10
) -> list[dict[str, Any]]:
    if policy.merger == "rrf":
        ranked = _rrf_merge(result_sets, policy.canonical_dedup)
    else:
        ranked = _raw_merge(result_sets, policy.canonical_dedup)
    if policy.per_domain_limit is not None:
        domain_counts: dict[str, int] = {}
        limited: list[dict[str, Any]] = []
        for item in ranked:
            identity = str(item.get("canonical_url") or item["url"])
            domain = urlsplit(identity).netloc.lower()
            if domain_counts.get(domain, 0) >= policy.per_domain_limit:
                continue
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            limited.append(item)
        ranked = limited
    return ranked[:limit]
