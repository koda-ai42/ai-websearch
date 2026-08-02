from __future__ import annotations

import math
from statistics import median
from urllib.parse import urlsplit


def safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def precision_recall(returned: list[str], relevant: set[str]) -> tuple[float, float]:
    hits = sum(item in relevant for item in returned)
    return safe_ratio(hits, len(returned)), safe_ratio(hits, len(relevant))


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for rank, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def ndcg(ranked: list[str], relevant: set[str]) -> float:
    gains = [1.0 if item in relevant else 0.0 for item in ranked]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal_count = min(len(relevant), len(ranked))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return safe_ratio(dcg, ideal)


def normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def duplicate_rate(texts: list[str]) -> float:
    if not texts:
        return 0.0
    unique = len({normalized_text(text) for text in texts})
    return safe_ratio(len(texts) - unique, len(texts))


def unique_domains(urls: list[str]) -> int:
    return len({urlsplit(url).netloc.lower() for url in urls if url})


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return float(ordered[index])


def latency_summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "p50_ms": float(median(values)) if values else 0.0,
        "p95_ms": percentile(values, 0.95),
    }


def mean(values: list[float]) -> float:
    return safe_ratio(sum(values), len(values))
