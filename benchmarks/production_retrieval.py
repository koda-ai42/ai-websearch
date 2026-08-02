from __future__ import annotations

import sqlite3
import time

from ai_websearch.retrieval import _minmax, fuse_ranked_scores
from ai_websearch.store import build_fts_query

CASES = (
    {
        "id": "semantic_only",
        "relevant": 1,
        "vector": {1: 0.92, 2: 0.72, 3: 0.61},
        "keyword": {},
    },
    {
        "id": "exact_identifier",
        "relevant": 1,
        "vector": {1: 0.60, 2: 0.95, 3: 0.80},
        "keyword": {1: 8.0},
    },
    {
        "id": "dual_channel",
        "relevant": 1,
        "vector": {2: 0.91, 1: 0.89, 3: 0.70},
        "keyword": {1: 5.0, 3: 2.0},
    },
)


def _legacy_fusion(vector: dict[int, float], keyword: dict[int, float]) -> list[int]:
    vector_norm = _minmax(vector)
    keyword_norm = _minmax(keyword)
    ids = set(vector) | set(keyword)
    scores = {
        item_id: 0.70 * vector_norm.get(item_id, 0.0) + 0.30 * keyword_norm.get(item_id, 0.0)
        for item_id in ids
    }
    return [
        item_id for item_id, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


def _mrr(order: list[int], relevant: int) -> float:
    return 1.0 / (order.index(relevant) + 1) if relevant in order else 0.0


def _fts_direction() -> dict:
    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, title, text, url UNINDEXED, topic UNINDEXED)"
        )
        connection.executemany(
            "INSERT INTO chunks_fts VALUES(?, ?, ?, '', '')",
            (
                (1, "Quantum lattice", "quantum quantum quantum lattice evidence"),
                (2, "Other", "a passing mention of quantum in unrelated material"),
            ),
        )
        rows = connection.execute(
            """SELECT chunk_id, bm25(chunks_fts, 0.0, 2.0, 1.0, 0.0, 0.0) rank
               FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank""",
            (build_fts_query('What is "quantum: lattice"?'),),
        ).fetchall()
    raw = {int(row[0]): float(row[1]) for row in rows}
    legacy = sorted(raw, key=lambda item_id: (-(1.0 / (1.0 + abs(raw[item_id]))), item_id))
    corrected = sorted(raw, key=lambda item_id: (raw[item_id], item_id))
    return {
        "relevant_chunk": 1,
        "legacy_order": legacy,
        "implemented_order": corrected,
        "legacy_reciprocal_rank": _mrr(legacy, 1),
        "implemented_reciprocal_rank": _mrr(corrected, 1),
        "safe_query": build_fts_query('What is "quantum: lattice"?'),
    }


def run_production_retrieval_benchmark(*, include_timing: bool = False) -> dict:
    started = time.perf_counter()
    rows = []
    for case in CASES:
        legacy = _legacy_fusion(case["vector"], case["keyword"])
        implemented_scores, _diagnostics = fuse_ranked_scores(case["vector"], case["keyword"])
        implemented = [
            item_id
            for item_id, _score in sorted(
                implemented_scores.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        rows.append(
            {
                "id": case["id"],
                "relevant_chunk": case["relevant"],
                "legacy_order": legacy,
                "implemented_order": implemented,
                "legacy_reciprocal_rank": _mrr(legacy, case["relevant"]),
                "implemented_reciprocal_rank": _mrr(implemented, case["relevant"]),
            }
        )
    fts = _fts_direction()
    elapsed = (time.perf_counter() - started) * 1000
    return {
        "schema_version": "1.0",
        "run_mode": "offline_production_helpers",
        "implementation": "schema-v3-rank-fusion",
        "accuracy": {
            "legacy_mean_reciprocal_rank": sum(row["legacy_reciprocal_rank"] for row in rows)
            / len(rows),
            "implemented_mean_reciprocal_rank": sum(
                row["implemented_reciprocal_rank"] for row in rows
            )
            / len(rows),
            "fts_legacy_reciprocal_rank": fts["legacy_reciprocal_rank"],
            "fts_implemented_reciprocal_rank": fts["implemented_reciprocal_rank"],
        },
        "reliability": {
            "cases_evaluated": len(rows) + 1,
            "uses_production_query_builder": True,
            "uses_production_fusion": True,
            "network_access": False,
            "model_inference": False,
        },
        "latency": {
            "measured": include_timing,
            "total_ms": round(elapsed, 4) if include_timing else None,
            "scope": "SQLite FTS fixture and in-process fusion only",
        },
        "fts": fts,
        "fusion_cases": rows,
        "limitations": [
            "Dense embeddings and CrossEncoder inference are held fixed and are not timed.",
            "Live SearXNG, Chromium, llama.cpp, and WebUI are not exercised.",
        ],
    }
