from __future__ import annotations

import asyncio
import inspect
import math
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from ai_websearch.config import Settings, settings
from ai_websearch.context_packer import _select
from ai_websearch.errors import (
    InvalidRerankingScoreError,
    RerankerInitializationError,
    RerankingError,
    RerankingScoreCountError,
)
from ai_websearch.models import ContextChunk
from ai_websearch.reranking import RerankerService
from ai_websearch.retrieval import _deduplicate_candidates
from ai_websearch.retrieval_policy import RetrievalLimits, resolve_research_mode_limits


def chunk(name: str, rank: int, source: int | None = None) -> ContextChunk:
    return ContextChunk(
        chunk_id=rank,
        source_id=source or rank,
        url=f"https://{name}.test",
        title=name,
        fetched_at="2026-01-01",
        chunk_index=0,
        text=f"distinct evidence passage {name}",
        score=1.0 - rank / 10,
        vector_score=0.9 - rank / 10,
        keyword_score=0.8 - rank / 10,
        pre_rerank_rank=rank,
    )


class FakeModel:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        if isinstance(self.scores, Exception):
            raise self.scores
        return self.scores


@pytest.fixture(autouse=True)
def restore_settings():
    values = {
        key: getattr(settings, key)
        for key in ("reranking_mode", "reranking_model", "reranking_candidates")
    }
    yield
    for key, value in values.items():
        setattr(settings, key, value)


def test_default_and_invalid_configuration() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.reranking_mode == "cross_encoder"
    assert len(defaults.embedding_model_revision) == 40
    assert len(defaults.reranking_model_revision) == 40
    with pytest.raises(ValidationError, match="RERANKING_MODE"):
        Settings(_env_file=None, reranking_mode="automatic")
    with pytest.raises(ValidationError, match="positive"):
        Settings(_env_file=None, reranking_candidates=0)
    with pytest.raises(ValidationError, match="commit hashes"):
        Settings(_env_file=None, embedding_model_revision="main")


def test_off_preserves_hybrid_order_and_skips_both_rerankers() -> None:
    settings.reranking_mode = "off"
    invoked = False

    def heuristic(_):
        nonlocal invoked
        invoked = True
        raise AssertionError

    service = RerankerService(
        model_factory=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError()), heuristic=heuristic
    )
    candidates = [chunk("A", 1), chunk("B", 2), chunk("C", 3)]
    ranked, metadata = asyncio.run(service.rank("q", candidates, 3))
    assert [item.title for item in ranked] == ["A", "B", "C"]
    assert not invoked and metadata["candidates_scored"] == 0
    assert all(item.rerank_score is None for item in ranked)


def test_cross_encoder_controls_order_and_bounds_candidates() -> None:
    settings.reranking_mode = "cross_encoder"
    model = FakeModel([0.10, 0.95, 0.40])
    service = RerankerService(model_factory=lambda *_a, **_k: model)
    ranked, metadata = asyncio.run(
        service.rank("query", [chunk("A", 1), chunk("B", 2), chunk("C", 3), chunk("D", 4)], 3)
    )
    assert [item.title for item in ranked] == ["B", "C", "A"]
    assert len(model.calls[0][0]) == 3
    assert metadata["candidates_received"] == 4 and metadata["candidates_scored"] == 3
    assert ranked[0].pre_rerank_rank == 2 and ranked[0].vector_score == pytest.approx(0.7)


def test_cross_encoder_loads_the_pinned_revision() -> None:
    settings.reranking_mode = "cross_encoder"
    observed = {}

    def factory(_model, **kwargs):
        observed.update(kwargs)
        return FakeModel([1.0])

    service = RerankerService(model_factory=factory)
    asyncio.run(service.initialize())
    assert observed["revision"] == settings.reranking_model_revision


def test_heuristic_only_and_failure_does_not_fall_back() -> None:
    settings.reranking_mode = "heuristic"
    scores = {"A": 0.1, "B": 0.95, "C": 0.4}
    service = RerankerService(
        model_factory=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError()),
        heuristic=lambda item: scores[item.title],
    )
    ranked, metadata = asyncio.run(
        service.rank("q", [chunk("A", 1), chunk("B", 2), chunk("C", 3)], 3)
    )
    assert [item.title for item in ranked] == ["B", "C", "A"]
    assert metadata["mode"] == "heuristic" and metadata["candidates_scored"] == 3
    failing = RerankerService(heuristic=lambda _item: (_ for _ in ()).throw(MemoryError()))
    with pytest.raises(RerankingError, match="Heuristic"):
        asyncio.run(failing.rank("q", [chunk("A", 1)], 1))


@pytest.mark.parametrize(
    "scores,error",
    [
        ([0.1], RerankingScoreCountError),
        ([math.nan, 0.2], InvalidRerankingScoreError),
        ([math.inf, 0.2], InvalidRerankingScoreError),
    ],
)
def test_invalid_cross_encoder_outputs_are_errors(scores, error) -> None:
    settings.reranking_mode = "cross_encoder"
    service = RerankerService(model_factory=lambda *_a, **_k: FakeModel(scores))
    with pytest.raises(error):
        asyncio.run(service.rank("q", [chunk("A", 1), chunk("B", 2)], 2))


def test_cross_encoder_inference_and_initialization_never_fall_back() -> None:
    settings.reranking_mode = "cross_encoder"
    service = RerankerService(model_factory=lambda *_a, **_k: FakeModel(MemoryError("oom")))
    with pytest.raises(RerankingError, match="CrossEncoder"):
        asyncio.run(service.rank("q", [chunk("A", 1)], 1))
    broken = RerankerService(
        model_factory=lambda *_a, **_k: (_ for _ in ()).throw(OSError("secret path"))
    )
    with pytest.raises(RerankerInitializationError) as raised:
        asyncio.run(broken.initialize())
    assert "secret path" not in str(raised.value.to_dict())


@pytest.mark.parametrize("mode", ["off", "heuristic"])
def test_non_cross_encoder_startup_does_not_load_model(mode) -> None:
    settings.reranking_mode = mode
    service = RerankerService(
        model_factory=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError())
    )
    asyncio.run(service.initialize())
    assert service._model is None


def test_mcp_signatures_still_have_no_reranker_parameter() -> None:
    from ai_websearch import server

    assert "reranking_mode" not in inspect.signature(server.research).parameters
    assert "reranking_mode" not in inspect.signature(server.retrieve_context).parameters


def test_research_and_retrieve_context_share_configured_reranking_path() -> None:
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).parents[1] / "src/ai_websearch/orchestrator.py").read_text())
    calls = {}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in {
            "research",
            "_run_research_pass",
            "_refresh_evidence",
            "retrieve_context",
        }:
            calls[node.name] = [
                child.func.id
                for child in ast.walk(node)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            ]
    assert "_run_research_pass" in calls["research"]
    assert "_refresh_evidence" in calls["_run_research_pass"]
    assert "retrieve_and_rerank" in calls["_refresh_evidence"]
    assert "retrieve_and_rerank" in calls["retrieve_context"]


def test_reranker_configuration_is_not_embedding_database_compatibility_metadata() -> None:
    from pathlib import Path

    store_source = (Path(__file__).parents[1] / "src/ai_websearch/store.py").read_text()
    initialize_body = store_source.split("def initialize_database", 1)[1].split(
        "def ensure_embedding_metadata", 1
    )[0]
    assert "reranking_mode" not in initialize_body
    assert "reranking_model" not in initialize_body


def test_duplicates_are_removed_before_inference_and_selection_preserves_diversity() -> None:
    candidates = [
        chunk("A", 1, 1).model_copy(update={"text": "alpha evidence passage"}),
        chunk("A duplicate", 2, 1).model_copy(update={"text": "alpha evidence passage"}),
        chunk("B", 3, 1).model_copy(update={"text": "bravo supporting material"}),
        chunk("C", 4, 2).model_copy(update={"text": "charlie corroborating details"}),
        chunk("D", 5, 3).model_copy(update={"text": "delta independent findings"}),
    ]
    deduplicated = _deduplicate_candidates(candidates)
    assert [item.title for item in deduplicated] == ["A", "B", "C", "D"]
    limits = RetrievalLimits("context", 1, 1, 1, 4, 3, 24, 24, 2)
    selected = _select(deduplicated, limits)
    assert sum(item.source_id == 1 for item in selected) <= 2
    assert len({item.source_id for item in selected}) >= 2


def test_selection_never_exceeds_explicit_chunk_limit() -> None:
    limits = RetrievalLimits("context", 1, 1, 1, 1, 3, 24, 24, 3)
    candidates = [chunk("A", 1, 1), chunk("B", 2, 1), chunk("C", 3, 2)]
    assert [item.title for item in _select(candidates, limits)] == ["A"]


def test_context_selection_can_fill_calculated_chunk_limit() -> None:
    limits = RetrievalLimits("context", 1, 1, 1, 8, 4, 48, 24, 3)
    candidates = [
        chunk(f"item{index}", index, 1 + (index - 1) // 2).model_copy(
            update={"text": f"unique evidence material item{index}"}
        )
        for index in range(1, 9)
    ]
    selected = _select(candidates, limits)
    assert len(selected) == limits.max_chunks


def test_cross_encoder_bound_caps_scoring_and_final_selection() -> None:
    settings.reranking_mode = "cross_encoder"
    settings.reranking_candidates = 24
    limits = resolve_research_mode_limits(100_000, "deep")
    assert limits.max_chunks == 24


def test_small_cross_encoder_bound_caps_deep_requests() -> None:
    settings.reranking_mode = "cross_encoder"
    settings.reranking_candidates = 3
    limits = resolve_research_mode_limits(100_000, "deep")
    assert limits.max_chunks == 3


def test_retrieval_filters_and_deduplicates_before_top_k(monkeypatch) -> None:
    from ai_websearch import retrieval

    rows = [
        {
            "id": item_id,
            "embedding": item_id,
            "dim": 1,
            "source_id": item_id,
            "url": f"https://source-{item_id}.test",
            "canonical_url": None,
            "title": f"source {item_id}",
            "topic": None,
            "fetched_at": "2026-01-01",
            "published_at": None,
            "chunk_index": 0,
            "text": text,
        }
        for item_id, text in [
            (1, "blocked evidence"),
            (2, "duplicate evidence"),
            (3, "duplicate evidence"),
            (4, "valid evidence"),
        ]
    ]

    async def embed_query(_query):
        return np.array([1.0])

    monkeypatch.setattr(retrieval.embedder, "embed_query", embed_query)
    monkeypatch.setattr(retrieval, "fetch_all_chunks", lambda topic=None: rows)
    monkeypatch.setattr(
        retrieval, "blob_to_vector", lambda value, _dim: np.array([1.0 - value / 10])
    )
    monkeypatch.setattr(retrieval, "keyword_search", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        retrieval,
        "check_url",
        lambda url: SimpleNamespace(allowed=url != "https://source-1.test"),
    )

    selected = asyncio.run(retrieval.retrieve("query", top_k=2, candidate_k=4))
    assert [item.chunk_id for item in selected] == [2, 4]
    assert [item.pre_rerank_rank for item in selected] == [2, 4]


def test_tie_tolerance_uses_original_rank_for_effective_ties() -> None:
    settings.reranking_mode = "heuristic"
    candidates = [chunk("A", 1), chunk("B", 2)]
    service = RerankerService(heuristic=lambda item: 0.5 if item.title == "A" else 0.5 + 0.5e-6)
    ranked, _ = asyncio.run(service.rank("q", candidates, 2))
    assert [item.title for item in ranked] == ["A", "B"]
