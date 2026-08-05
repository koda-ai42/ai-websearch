from __future__ import annotations

import math

import numpy as np

from .config import settings
from .content_quality import assess_content_quality
from .embeddings import embedder
from .freshness import freshness_score
from .models import ContextChunk
from .reranking import reranker
from .store import blob_to_vector, fetch_all_chunks, keyword_search
from .url_policy import check_url


def _minmax(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    values = list(scores.values())
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return {key: 1.0 for key in scores}
    return {key: (value - low) / (high - low) for key, value in scores.items()}


def _rank_map(scores: dict[int, float]) -> dict[int, int]:
    ranked: dict[int, int] = {}
    previous_score: float | None = None
    previous_rank = 0
    for position, (chunk_id, score) in enumerate(
        sorted(scores.items(), key=lambda item: (-item[1], item[0])),
        1,
    ):
        if previous_score is None or not math.isclose(
            score,
            previous_score,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            previous_rank = position
        ranked[chunk_id] = previous_rank
        previous_score = score
    return ranked


def fuse_ranked_scores(
    vector_scores: dict[int, float],
    keyword_scores: dict[int, float],
    freshness_values: dict[int, float | None] | None = None,
) -> tuple[dict[int, float], dict[str, dict[int, float] | dict[int, int]]]:
    """Fuse heterogeneous retrieval channels by rank, retaining legacy diagnostics."""

    vector_norm, keyword_norm = _minmax(vector_scores), _minmax(keyword_scores)
    vector_ranks, keyword_ranks = _rank_map(vector_scores), _rank_map(keyword_scores)
    candidate_ids = set(vector_scores) | set(keyword_scores)
    original_hybrid: dict[int, float] = {}
    rank_fused: dict[int, float] = {}
    for chunk_id in candidate_ids:
        original_hybrid[chunk_id] = settings.vector_weight * vector_norm.get(
            chunk_id, 0.0
        ) + settings.keyword_weight * keyword_norm.get(chunk_id, 0.0)
        score = 0.0
        if chunk_id in vector_ranks:
            score += settings.vector_weight / (60.0 + vector_ranks[chunk_id])
        if chunk_id in keyword_ranks:
            score += settings.keyword_weight / (60.0 + keyword_ranks[chunk_id])
        rank_fused[chunk_id] = score

    normalized_fusion = _minmax(rank_fused)
    final_scores: dict[int, float] = {}
    freshness_values = freshness_values or {}
    for chunk_id, score in normalized_fusion.items():
        fresh = freshness_values.get(chunk_id)
        final_scores[chunk_id] = score if fresh is None else 0.90 * score + 0.10 * fresh
    return final_scores, {
        "vector_normalized": vector_norm,
        "keyword_normalized": keyword_norm,
        "vector_ranks": vector_ranks,
        "keyword_ranks": keyword_ranks,
        "original_hybrid": original_hybrid,
        "original_hybrid_ranks": _rank_map(original_hybrid),
    }


async def retrieve(
    query: str,
    topic: str | None = None,
    top_k: int = 8,
    candidate_k: int | None = None,
    freshness: str | None = None,
) -> list[ContextChunk]:
    top_k = max(1, min(top_k, 1000))
    candidate_k = max(top_k, min(candidate_k or max(50, top_k * 5), 2000))
    rows = fetch_all_chunks(topic=topic)
    if not rows:
        return []
    query_vector = await embedder.embed_query(query)
    row_lookup = {int(row["id"]): row for row in rows}
    vector_scores: dict[int, float] = {}
    for row in rows:
        chunk_id = int(row["id"])
        vector = blob_to_vector(row["embedding"], int(row["dim"]))
        if vector.shape[0] != query_vector.shape[0]:
            raise RuntimeError(
                f"Stored embedding dimension {vector.shape[0]} does not match query dimension {query_vector.shape[0]}; rebuild the database."
            )
        vector_scores[chunk_id] = float(np.dot(query_vector, vector))

    keyword_scores = keyword_search(query, top_k=candidate_k, topic=topic)
    top_vector = dict(
        sorted(vector_scores.items(), key=lambda item: item[1], reverse=True)[:candidate_k]
    )
    candidate_ids = set(top_vector) | set(keyword_scores)
    freshness_values: dict[int, float | None] = {}
    for chunk_id in candidate_ids:
        candidate_row = row_lookup.get(chunk_id)
        fresh = freshness_score(
            candidate_row["published_at"] if candidate_row else None,
            freshness=freshness,
        )
        freshness_values[chunk_id] = fresh
    fused, diagnostics = fuse_ranked_scores(top_vector, keyword_scores, freshness_values)
    vector_norm = diagnostics["vector_normalized"]
    keyword_norm = diagnostics["keyword_normalized"]
    vector_ranks = diagnostics["vector_ranks"]
    keyword_ranks = diagnostics["keyword_ranks"]
    original_hybrid = diagnostics["original_hybrid"]
    original_ranks = diagnostics["original_hybrid_ranks"]

    ranked_ids = [
        chunk_id for chunk_id, _ in sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    ]
    output: list[ContextChunk] = []
    for rank, chunk_id in enumerate(ranked_ids, 1):
        candidate_row = row_lookup.get(chunk_id)
        if not candidate_row:
            continue
        candidate = ContextChunk(
            chunk_id=chunk_id,
            source_id=int(candidate_row["source_id"]),
            url=candidate_row["url"],
            canonical_url=candidate_row["canonical_url"],
            title=candidate_row["title"] or "",
            topic=topic or candidate_row["topic"],
            fetched_at=candidate_row["fetched_at"],
            published_at=candidate_row["published_at"],
            published_at_source=(
                candidate_row["published_at_source"]
                if "published_at_source" in candidate_row.keys()
                else None
            ),
            chunk_index=int(candidate_row["chunk_index"]),
            text=candidate_row["text"],
            score=float(fused.get(chunk_id, 0.0)),
            vector_score=float(vector_norm.get(chunk_id, 0.0)),
            keyword_score=float(keyword_norm.get(chunk_id, 0.0)),
            freshness_score=freshness_values.get(chunk_id),
            vector_rank=vector_ranks.get(chunk_id),
            keyword_rank=keyword_ranks.get(chunk_id),
            original_hybrid_score=float(original_hybrid.get(chunk_id, 0.0)),
            original_hybrid_rank=original_ranks.get(chunk_id),
            pre_rerank_rank=rank,
        )
        if not check_url(candidate.canonical_url or candidate.url).allowed:
            continue
        output.append(candidate)
    return _deduplicate_candidates(output)[:top_k]


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in text
        ).split()
        if len(token) > 2
    }


def _deduplicate_candidates(
    candidates: list[ContextChunk], threshold: float = 0.92
) -> list[ContextChunk]:
    selected: list[ContextChunk] = []
    fingerprints: set[str] = set()
    token_sets: list[set[str]] = []
    for candidate in candidates:
        fingerprint = " ".join(candidate.text.lower().split())
        if fingerprint in fingerprints:
            continue
        tokens = _tokens(candidate.text)
        if any(
            tokens and prior and len(tokens & prior) / len(tokens | prior) >= threshold
            for prior in token_sets
        ):
            continue
        fingerprints.add(fingerprint)
        token_sets.append(tokens)
        selected.append(candidate)
    return selected


async def retrieve_and_rerank(
    query: str,
    topic: str | None = None,
    top_k: int = 8,
    candidate_k: int | None = None,
    reranking_candidates: int | None = None,
    freshness: str | None = None,
) -> tuple[list[ContextChunk], dict]:
    candidates = await retrieve(query, topic, top_k, candidate_k, freshness)
    effective_limit = min(len(candidates), reranking_candidates or settings.reranking_candidates)
    filtered, filter_metadata = _filter_for_reranking(query, candidates, effective_limit)
    ranked, metadata = await reranker.rank(query, filtered, len(filtered))
    return ranked, {**metadata, **filter_metadata}


def _filter_for_reranking(
    query: str,
    candidates: list[ContextChunk],
    limit: int,
) -> tuple[list[ContextChunk], dict]:
    query_tokens = _tokens(query)
    selected: list[ContextChunk] = []
    rejected = {
        "content_quality": 0,
        "too_short": 0,
        "low_query_coverage": 0,
        "candidate_bound": 0,
    }
    for candidate in candidates:
        if len(selected) >= limit:
            rejected["candidate_bound"] += 1
            continue
        quality = assess_content_quality(candidate.title, candidate.text)
        if not quality.usable:
            rejected["content_quality"] += 1
            continue
        if len(candidate.text.strip()) < 24:
            rejected["too_short"] += 1
            continue
        passage_tokens = _tokens(candidate.title + " " + candidate.text)
        has_any_channel = candidate.vector_rank is not None or candidate.keyword_rank is not None
        if query_tokens and not (query_tokens & passage_tokens) and not has_any_channel:
            rejected["low_query_coverage"] += 1
            continue
        selected.append(candidate)
    return selected, {
        "candidates_before_filter": len(candidates),
        "candidates_after_filter": len(selected),
        "filter_rejections": rejected,
    }
