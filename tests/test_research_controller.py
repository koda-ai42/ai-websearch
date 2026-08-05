from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ai_websearch import orchestrator
from ai_websearch.config import Settings
from ai_websearch.context_packer import _final_research_metadata
from ai_websearch.models import ContextChunk, IngestResult, SearchResult
from ai_websearch.research_controller import assess_evidence, initial_pass, query_is_complex
from ai_websearch.retrieval_policy import (
    calculate_context_retrieval_limits,
    evidence_checkpoints,
    resolve_research_mode_limits,
)


def _chunk(source_id: int, text: str, *, dual_channel: bool = True) -> ContextChunk:
    return ContextChunk(
        chunk_id=source_id,
        source_id=source_id,
        url=f"https://s{source_id}.test/article",
        title="Relevant evidence",
        fetched_at="2026-08-01T00:00:00Z",
        chunk_index=0,
        text=text,
        score=1.0,
        vector_rank=source_id,
        keyword_rank=source_id if dual_channel else None,
    )


def test_auto_always_starts_rapid_and_complexity_is_still_assessed() -> None:
    assert initial_pass("auto") == "rapid"
    assert initial_pass("rapid") == "rapid"
    assert initial_pass("deep") == "deep"
    assert query_is_complex("What is alpha? Explain beta; Describe gamma")


def test_evidence_gate_stops_on_relevant_dual_channel_result() -> None:
    result = assess_evidence(
        "How does hybrid retrieval work?",
        [_chunk(1, "Hybrid retrieval combines dense vector and keyword retrieval evidence.")],
    )
    assert result.sufficient
    assert result.reason == "sufficient_evidence"


def test_dual_channel_alone_cannot_override_low_query_coverage() -> None:
    result = assess_evidence(
        "orbital transfer window calculation",
        [_chunk(1, "Unrelated substantive engineering discussion with no matching terms.")],
    )
    assert not result.sufficient
    assert result.reason == "low_query_coverage"


def test_low_coverage_dual_channel_requires_source_diversity() -> None:
    result = assess_evidence(
        "orbital transfer window calculation",
        [
            _chunk(1, "A substantive semantic explanation using different terminology."),
            _chunk(2, "Independent corroboration also uses different terminology."),
        ],
    )
    assert result.sufficient


def test_complex_evidence_gate_requires_source_diversity() -> None:
    result = assess_evidence(
        "What is alpha? Explain beta; Describe gamma",
        [_chunk(1, "Alpha and beta have several trade-offs.")],
    )
    assert not result.sufficient
    assert result.reason == "complex_query_needs_source_diversity"


def test_final_packed_selection_replaces_prepack_answerability() -> None:
    query = "What is alpha? Explain beta; Describe gamma"
    metadata = {
        "stop_reason": "sufficient_evidence",
        "evidence_assessment": {
            "sufficient": True,
            "reason": "sufficient_evidence",
            "source_count": 2,
            "chunk_count": 2,
            "query_coverage": 1.0,
        },
        "answerability": {
            "answerable": True,
            "required_action": "answer_with_citations",
        },
    }
    updated = _final_research_metadata(
        query,
        [_chunk(1, "Alpha and beta have measured trade-offs.")],
        metadata,
    )
    assert updated is not None
    assert updated["pre_pack_evidence_assessment"]["sufficient"] is True
    assert updated["final_evidence_assessment"]["sufficient"] is False
    assert updated["answerability"] == {
        "answerable": False,
        "required_action": "state_insufficient_evidence",
    }
    assert updated["stop_reason"] == "packed_evidence_insufficient"


def test_explicit_rapid_never_escalates(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    monkeypatch.setattr(orchestrator, "search_many", _empty_search)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", _empty_retrieval)

    captured: dict = {}

    async def fake_pack(*args, **_kwargs):
        captured.update(args[-1])
        return captured

    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)
    result = asyncio.run(orchestrator.research("simple question", mode="rapid"))
    assert result["mode_used"] == "rapid"
    assert result["escalated"] is False
    assert result["answerability"] == {
        "answerable": False,
        "required_action": "state_insufficient_evidence",
    }
    assert len(result["passes"]) == 1


def test_auto_escalates_at_most_once(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    monkeypatch.setattr(orchestrator, "search_many", _empty_search)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", _empty_retrieval)

    async def fake_pack(*args, **_kwargs):
        return args[-1]

    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)
    result = asyncio.run(orchestrator.research("simple question", mode="auto"))
    assert result["mode_used"] == "deep"
    assert result["escalated"] is True
    assert result["escalation_reason"] == "no_usable_evidence"
    assert len(result["passes"]) == 2


def test_auto_escalates_when_one_dual_channel_source_has_low_coverage(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    monkeypatch.setattr(orchestrator, "search_many", _empty_search)

    async def low_coverage(*_args, **_kwargs):
        return [_chunk(1, "Substantive material expressed with unrelated terminology.")], {}

    async def fake_pack(*args, **_kwargs):
        return args[-1]

    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", low_coverage)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)
    result = asyncio.run(orchestrator.research("orbital transfer window calculation", mode="auto"))
    assert result["mode_used"] == "deep"
    assert result["escalated"] is True
    assert result["escalation_reason"] == "low_query_coverage"


def test_evidence_assessment_uses_packable_chunk_selection(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    monkeypatch.setattr(orchestrator, "search_many", _empty_search)
    base = _chunk(1, "Simple question evidence alpha with sufficient relevant detail.")

    async def candidates(*_args, **_kwargs):
        texts = [
            "Simple question evidence describes material composition and laboratory notes.",
            "Simple question evidence reports deployment timing and operational findings.",
            "Simple question evidence documents maintenance costs and observed reliability.",
        ]
        return [
            base.model_copy(update={"chunk_id": index, "chunk_index": index, "text": text})
            for index, text in enumerate(texts)
        ], {}

    async def fake_pack(*args, **_kwargs):
        return args[-1]

    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", candidates)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)
    result = asyncio.run(orchestrator.research("simple question", mode="rapid"))
    assert result["evidence_assessment"]["chunk_count"] == 3
    assert result["passes"][0]["evidence"]["chunk_count"] == 3
    assert result["answerability"] == {
        "answerable": True,
        "required_action": "answer_with_citations",
    }


def test_mode_defaults_are_explicit_and_distinct(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator.settings, "reranking_mode", "cross_encoder")
    monkeypatch.setattr(orchestrator.settings, "reranking_candidates", 24)
    monkeypatch.setattr(orchestrator.settings, "research_max_page_attempts_hard_limit", 20)

    assert resolve_research_mode_limits(100_000, "rapid").effective_metadata() == {
        "max_page_attempts": 2,
        "max_sources": 2,
        "max_chunks": 8,
    }
    assert resolve_research_mode_limits(100_000, "auto").effective_metadata() == {
        "max_page_attempts": 5,
        "max_sources": 5,
        "max_chunks": 15,
    }
    assert resolve_research_mode_limits(100_000, "deep").effective_metadata() == {
        "max_page_attempts": 10,
        "max_sources": 8,
        "max_chunks": 24,
    }


def test_requested_limits_can_only_tighten_mode_defaults(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator.settings, "research_max_page_attempts_hard_limit", 20)
    deep = resolve_research_mode_limits(
        100_000,
        "deep",
        requested_max_page_attempts=5,
        requested_max_sources=4,
        requested_max_chunks=12,
    )
    assert deep.effective_metadata() == {
        "max_page_attempts": 5,
        "max_sources": 4,
        "max_chunks": 12,
    }
    rapid = resolve_research_mode_limits(
        100_000,
        "rapid",
        requested_max_page_attempts=10,
        requested_max_sources=100,
        requested_max_chunks=100,
    )
    assert rapid.effective_metadata() == {
        "max_page_attempts": 2,
        "max_sources": 2,
        "max_chunks": 8,
    }
    assert deep.requested_metadata() == {
        "max_page_attempts": 5,
        "max_sources": 4,
        "max_chunks": 12,
    }
    assert deep.metadata() == {
        "mode_defaults": {
            "max_page_attempts": 10,
            "max_sources": 8,
            "max_chunks": 24,
        },
        "requested": {
            "max_page_attempts": 5,
            "max_sources": 4,
            "max_chunks": 12,
        },
        "effective": {
            "max_page_attempts": 5,
            "max_sources": 4,
            "max_chunks": 12,
        },
        "absolute_max_page_attempts": 20,
    }


def test_absolute_page_limit_can_tighten_every_mode(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator.settings, "research_max_page_attempts_hard_limit", 4)
    assert resolve_research_mode_limits(100_000, "rapid").max_page_attempts == 2
    assert resolve_research_mode_limits(100_000, "auto").max_page_attempts == 4
    assert resolve_research_mode_limits(100_000, "deep").max_page_attempts == 4


def test_context_retrieval_uses_only_numeric_limits(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator.settings, "reranking_mode", "cross_encoder")
    monkeypatch.setattr(orchestrator.settings, "reranking_candidates", 24)
    limits = calculate_context_retrieval_limits(
        100_000,
        top_k=12,
        requested_max_sources=4,
        requested_max_chunks=10,
    )
    assert limits.name == "context"
    assert limits.retrieve_candidates == 12
    assert limits.max_sources == 4
    assert limits.max_chunks == 10


def test_evidence_checkpoints_are_bounded_staged_waves() -> None:
    assert evidence_checkpoints(0) == ()
    assert evidence_checkpoints(1) == (1,)
    assert evidence_checkpoints(2) == (2,)
    assert evidence_checkpoints(3) == (2, 3)
    assert evidence_checkpoints(10) == (2, 5, 10)


def test_hard_page_limit_configuration_must_stay_in_safe_range() -> None:
    with pytest.raises(ValueError, match="between 1 and 20"):
        Settings(_env_file=None, research_max_page_attempts_hard_limit=0)
    with pytest.raises(ValueError, match="between 1 and 20"):
        Settings(_env_file=None, research_max_page_attempts_hard_limit=21)


def test_auto_page_limit_is_shared_across_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    calls = 0

    async def fake_search(*_args, **_kwargs):
        return _search_batch(
            [
                SearchResult(
                    title=f"source {index}", url=f"https://s{index}.test/article", score=1.0
                )
                for index in range(10)
            ]
        )

    async def fake_ingest(url, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        return IngestResult(ok=True, url=url)

    async def fake_pack(*args, **_kwargs):
        return args[-1]

    monkeypatch.setattr(orchestrator, "search_many", fake_search)
    monkeypatch.setattr(orchestrator, "ingest_url", fake_ingest)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", _empty_retrieval)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)

    result = asyncio.run(orchestrator.research("simple question", mode="auto"))

    assert calls == 5
    assert [item["new_pages_attempted"] for item in result["passes"]] == [2, 3]
    assert result["unique_urls_considered"] == 5
    assert result["limits"]["effective"] == {
        "max_page_attempts": 5,
        "max_sources": 5,
        "max_chunks": 15,
    }


def test_complex_auto_starts_rapid_then_uses_remaining_request_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    attempted: list[str] = []

    async def fake_search(*_args, **_kwargs):
        return _search_batch(
            [
                SearchResult(
                    title=f"source {index}", url=f"https://s{index}.test/article", score=1.0
                )
                for index in range(10)
            ]
        )

    async def fake_ingest(url, *_args, **_kwargs):
        attempted.append(url)
        return IngestResult(ok=True, url=url)

    async def fake_pack(*args, **_kwargs):
        return args[-1]

    monkeypatch.setattr(orchestrator, "search_many", fake_search)
    monkeypatch.setattr(orchestrator, "ingest_url", fake_ingest)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", _empty_retrieval)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)

    result = asyncio.run(
        orchestrator.research(
            "Compare alpha versus beta and evaluate their trade-offs", mode="auto"
        )
    )

    assert result["mode_used"] == "deep"
    assert len(attempted) == 5
    assert [item["page_attempt_limit"] for item in result["passes"]] == [2, 3]


def test_auto_escalation_cannot_borrow_unused_rapid_attempts(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    searches = 0
    attempted: list[str] = []

    async def fake_search(*_args, **_kwargs):
        nonlocal searches
        searches += 1
        if searches == 1:
            return _search_batch([])
        return _search_batch(
            [
                SearchResult(
                    title=f"source {index}", url=f"https://s{index}.test/article", score=1.0
                )
                for index in range(10)
            ]
        )

    async def fake_ingest(url, *_args, **_kwargs):
        attempted.append(url)
        return IngestResult(ok=True, url=url)

    async def fake_pack(*args, **_kwargs):
        return args[-1]

    monkeypatch.setattr(orchestrator, "search_many", fake_search)
    monkeypatch.setattr(orchestrator, "ingest_url", fake_ingest)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", _empty_retrieval)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)

    result = asyncio.run(orchestrator.research("simple question", mode="auto"))

    assert len(attempted) == 3
    assert [item["page_attempt_limit"] for item in result["passes"]] == [2, 3]
    assert result["unique_urls_considered"] == 3


def test_deep_stops_at_a_staged_checkpoint_when_evidence_is_sufficient(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime, "get", lambda: _async(SimpleNamespace(context_tokens=65536))
    )
    attempted: list[str] = []

    async def fake_search(*_args, **_kwargs):
        return _search_batch(
            [
                SearchResult(
                    title=f"source {index}", url=f"https://s{index}.test/article", score=1.0
                )
                for index in range(10)
            ]
        )

    async def fake_ingest(url, *_args, **_kwargs):
        attempted.append(url)
        return IngestResult(ok=True, url=url)

    async def sufficient_retrieval(*_args, **_kwargs):
        return [_chunk(1, "Simple question evidence from a dual-channel result.")], {}

    async def fake_pack(*args, **_kwargs):
        return args[-1]

    monkeypatch.setattr(orchestrator, "search_many", fake_search)
    monkeypatch.setattr(orchestrator, "ingest_url", fake_ingest)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", sufficient_retrieval)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)

    result = asyncio.run(orchestrator.research("simple question", mode="deep"))

    assert len(attempted) == 2
    assert result["stop_reason"] == "sufficient_evidence"
    assert result["passes"][0]["page_attempt_limit"] == 10
    assert result["passes"][0]["new_pages_attempted"] == 2
    assert result["passes"][0]["evidence_checks"] == 1


def test_search_is_cancelled_at_the_remaining_request_deadline(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime,
        "get",
        lambda: _async(SimpleNamespace(context_tokens=65536)),
    )
    monkeypatch.setattr(orchestrator.settings, "rapid_research_max_seconds", 0.01)

    async def slow_search(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return _search_batch([])

    async def fake_pack(*args, **_kwargs):
        payload = dict(args[-1])
        payload["warnings"] = args[-3]
        return payload

    monkeypatch.setattr(orchestrator, "search_many", slow_search)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", _empty_retrieval)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)

    result = asyncio.run(orchestrator.research("simple question", mode="rapid"))
    assert result["stop_reason"] == "time_budget_reached"
    assert result["passes"][0]["search"]["deadline_exceeded"] is True
    assert "expired during web search" in result["warnings"][0]


def test_ingestion_is_cancelled_at_the_remaining_request_deadline(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator.runtime,
        "get",
        lambda: _async(SimpleNamespace(context_tokens=65536)),
    )
    monkeypatch.setattr(orchestrator.settings, "rapid_research_max_seconds", 0.01)

    async def one_result(*_args, **_kwargs):
        return _search_batch(
            [SearchResult(title="slow", url="https://slow.test/article", score=1.0)]
        )

    async def slow_ingest(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return IngestResult(ok=True, url="https://slow.test/article")

    async def fake_pack(*args, **_kwargs):
        payload = dict(args[-1])
        payload["warnings"] = args[-3]
        return payload

    monkeypatch.setattr(orchestrator, "search_many", one_result)
    monkeypatch.setattr(orchestrator, "ingest_url", slow_ingest)
    monkeypatch.setattr(orchestrator, "retrieve_and_rerank", _empty_retrieval)
    monkeypatch.setattr(orchestrator, "pack_context", fake_pack)

    result = asyncio.run(orchestrator.research("simple question", mode="rapid"))
    assert result["stop_reason"] == "time_budget_reached"
    assert result["blocked_access_outcomes"] == {"deadline_exceeded": 1}
    assert result["passes"][0]["new_pages_attempted"] == 1


def test_invalid_requested_research_limit_is_rejected() -> None:
    for field in ("requested_max_page_attempts", "requested_max_sources", "requested_max_chunks"):
        kwargs = {field: 0}
        try:
            resolve_research_mode_limits(100_000, "auto", **kwargs)
        except ValueError as exc:
            assert "positive integer" in str(exc)
        else:
            raise AssertionError(f"{field} accepted zero")


async def _async(value):
    return value


async def _empty_search(*_args, **_kwargs):
    return _search_batch([])


def _search_batch(results: list[SearchResult]) -> tuple[list[SearchResult], dict]:
    return results, {
        "queries_planned": 1,
        "queries_succeeded": 1,
        "queries_failed": 0,
        "partial_failure": False,
        "queries": [{"query_index": 0, "status": "ok", "result_count": len(results)}],
    }


async def _empty_retrieval(*_args, **_kwargs):
    return [], {"mode": "off"}
