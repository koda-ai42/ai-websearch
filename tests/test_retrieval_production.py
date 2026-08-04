from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest

from ai_websearch import orchestrator, store
from ai_websearch.config import settings
from ai_websearch.context_packer import _render_context
from ai_websearch.errors import SearchUnavailableError
from ai_websearch.freshness import (
    freshness_score,
    normalize_publication_date,
    parse_publication_date,
)
from ai_websearch.models import ContextChunk, SearchResult
from ai_websearch.orchestrator import plan_queries, search_many
from ai_websearch.retrieval import _filter_for_reranking, _rank_map
from ai_websearch.scrape import _published
from ai_websearch.search import _retryable_search_error


def _add_fts_row(connection, source_id: int, title: str, text: str) -> int:
    cursor = connection.execute(
        """INSERT INTO sources(
               id, url, canonical_url, title, domain, topic, fetched_at,
               published_at, content_hash, markdown
           ) VALUES (?, ?, ?, ?, ?, 'topic', '2026-01-01', NULL, ?, ?)""",
        (
            source_id,
            f"https://s{source_id}.test",
            f"https://s{source_id}.test",
            title,
            f"s{source_id}.test",
            f"h{source_id}",
            text,
        ),
    )
    assert cursor.rowcount == 1
    chunk = connection.execute(
        """INSERT INTO chunks(
               source_id, url, canonical_url, title, topic, fetched_at, published_at,
               chunk_index, text, text_hash, embedding, dim, token_estimate
           ) VALUES (?, ?, ?, ?, 'topic', '2026-01-01', NULL, 0, ?, ?, ?, 1, 1)""",
        (
            source_id,
            f"https://s{source_id}.test",
            f"https://s{source_id}.test",
            title,
            text,
            f"c{source_id}",
            np.array([1.0], dtype=np.float32).tobytes(),
        ),
    )
    chunk_id = int(chunk.lastrowid)
    connection.execute(
        "INSERT INTO chunks_fts(chunk_id, title, text, url, topic) VALUES (?, ?, ?, ?, 'topic')",
        (chunk_id, title, text, f"https://s{source_id}.test"),
    )
    return chunk_id


def test_real_fts_query_is_safe_and_preserves_bm25_direction(tmp_path: Path) -> None:
    path = tmp_path / "fts.sqlite3"
    original = settings.database_path
    settings.database_path = str(path)
    try:
        with store.connect() as connection:
            strong = _add_fts_row(
                connection, 1, "Quantum lattice", "quantum quantum quantum lattice evidence"
            )
            weak = _add_fts_row(
                connection,
                2,
                "Other",
                "a passing mention of quantum in a much longer unrelated passage",
            )
            connection.commit()
        scores = store.keyword_search('What is "quantum: lattice"?', topic="topic")
        assert strong in scores and weak in scores
        assert scores[strong] > scores[weak]
    finally:
        settings.database_path = original


def test_freshness_is_conditional_and_unknown_is_neutral() -> None:
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert parse_publication_date("2026-07-31T12:00:00Z") is not None
    assert freshness_score("2026-07-31", freshness="auto", now=now) is None
    assert freshness_score("2026-07-31", freshness=None, now=now) is None
    assert freshness_score(None, freshness=None, now=now) is None
    assert freshness_score(None, freshness="day", now=now) == 0.5
    recent = freshness_score("2026-07-31", freshness="day", now=now)
    old = freshness_score("2024-01-01", freshness="day", now=now)
    assert recent is not None and old is not None and recent > old


def test_parse_publication_date_international_formats() -> None:
    # ISO 8601
    d = parse_publication_date("2024-01-15")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 15
    d = parse_publication_date("2024-01-15T10:30Z")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 15

    # YYYY[-/.]M[-/.]D
    d = parse_publication_date("2024/01/15")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 15
    d = parse_publication_date("2024.1.5")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 5

    # D/M/YYYY with disambiguation
    d = parse_publication_date("15/1/2024")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 15
    d = parse_publication_date("5.1.2024")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 5
    # Ambiguous: both <= 12, default DD/MM/YYYY
    d = parse_publication_date("1/2/2024")
    assert d is not None and d.year == 2024 and d.month == 2 and d.day == 1
    # First > 12, clearly day
    d = parse_publication_date("25/12/2024")
    assert d is not None and d.year == 2024 and d.month == 12 and d.day == 25
    # Second > 12, clearly month is first
    d = parse_publication_date("1/25/2024")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 25

    # Year only
    d = parse_publication_date("2024")
    assert d is not None and d.year == 2024 and d.month == 1 and d.day == 1

    # Normalize rejects future dates
    assert normalize_publication_date("2030-01-01", "2026-08-02T00:00:00Z") is None


def test_freshness_window_removed() -> None:
    from ai_websearch.freshness import freshness_score as fs
    # Verify the removed functions no longer exist
    import ai_websearch.freshness as mod
    assert not hasattr(mod, "freshness_window")
    assert not hasattr(mod, "query_needs_freshness")
    assert not hasattr(mod, "TEMPORAL_TERMS")
    assert not hasattr(mod, "DAY_TERMS")
    assert not hasattr(mod, "MONTH_TERMS")


def test_json_ld_publication_date_has_explicit_provenance() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type": "Article", "datePublished": "2026-08-01T10:00:00Z"}
      </script>
      <meta property="article:published_time" content="2026-07-31T10:00:00Z">
    </head></html>
    """
    published, source = _published(html, "2026-08-02T00:00:00Z")
    assert published == "2026-08-01T10:00:00+00:00"
    assert source == "json_ld"


def test_future_json_ld_date_falls_through_to_valid_meta() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type": "Article", "datePublished": "2030-08-01T10:00:00Z"}
      </script>
      <meta name="date" content="2026-07-31T10:00:00Z">
    </head></html>
    """
    published, source = _published(html, "2026-08-02T00:00:00Z")
    assert published == "2026-07-31T10:00:00+00:00"
    assert source == "meta"


def test_query_planning_avoids_credibility_suffixes() -> None:
    planned = plan_queries("Compare alpha versus beta", 5)
    assert planned == ["Compare alpha versus beta"]
    assert all(
        "official source" not in query and "technical documentation" not in query
        for query in planned
    )
    # Multi-clause queries are split on punctuation (language-neutral)
    planned = plan_queries("What is alpha? Explain beta; Describe gamma", 5)
    assert planned == [
        "What is alpha? Explain beta; Describe gamma",
        "What is alpha",
        "Explain beta",
        "Describe gamma",
    ]


def test_cross_query_merge_uses_rank_not_raw_score(monkeypatch) -> None:
    async def fake_search(query: str, **_kwargs):
        return [
            SearchResult(url="https://answer.test", title="answer", score=0.01),
            SearchResult(url="https://other.test", title="other", score=0.9),
        ]

    monkeypatch.setattr(orchestrator, "web_search", fake_search)
    results, diagnostics = asyncio.run(search_many("answer status", 2, 5, "month", "en"))
    assert results[0].url == "https://answer.test"
    assert diagnostics["queries_succeeded"] == 1
    assert diagnostics["partial_failure"] is False


def test_cross_query_partial_failure_is_observable(monkeypatch) -> None:
    call_count = [0]

    async def fake_search(query: str, **_kwargs):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("synthetic outage")
        return [SearchResult(url="https://answer.test", title="answer", score=1.0)]

    monkeypatch.setattr(orchestrator, "web_search", fake_search)
    results, diagnostics = asyncio.run(search_many("answer status; second query here", 2, 5, None, "en"))
    assert [item.url for item in results] == ["https://answer.test"]
    assert diagnostics["queries_failed"] == 1
    assert diagnostics["queries_succeeded"] == 1
    assert diagnostics["partial_failure"] is True


def test_all_planned_search_failures_raise_typed_error(monkeypatch) -> None:
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("synthetic outage")

    monkeypatch.setattr(orchestrator, "web_search", unavailable)
    with pytest.raises(SearchUnavailableError) as captured:
        asyncio.run(search_many("answer status; second query", 2, 5, None, "en"))
    assert captured.value.code == "search_unavailable"
    assert captured.value.details == {"queries_planned": 2, "queries_failed": 2}


def test_search_retry_policy_accepts_only_transient_failures() -> None:
    request = httpx.Request("GET", "http://127.0.0.1:8888/search")
    assert _retryable_search_error(httpx.ConnectError("offline", request=request))
    for status in (408, 429, 500, 502, 503, 504):
        response = httpx.Response(status, request=request)
        assert _retryable_search_error(
            httpx.HTTPStatusError("transient", request=request, response=response)
        )
    for status in (400, 401, 403, 404):
        response = httpx.Response(status, request=request)
        assert not _retryable_search_error(
            httpx.HTTPStatusError("terminal", request=request, response=response)
        )


def _candidate(
    index: int, text: str, vector_rank: int | None, keyword_rank: int | None
) -> ContextChunk:
    return ContextChunk(
        chunk_id=index,
        source_id=index,
        url=f"https://s{index}.test",
        fetched_at="2026-01-01",
        chunk_index=0,
        text=text,
        score=1.0 / index,
        vector_rank=vector_rank,
        keyword_rank=keyword_rank,
        pre_rerank_rank=index,
    )


def test_pre_reranker_filter_never_forces_an_ineligible_minimum_pool() -> None:
    candidates = [_candidate(index, f"short {index}", index, None) for index in range(1, 10)]
    candidates.append(_candidate(10, "long unrelated material. " * 10, 10, 10))
    selected, metadata = _filter_for_reranking("answer terms", candidates, 10)
    assert [item.chunk_id for item in selected] == [10]
    assert metadata["candidates_before_filter"] == 10
    assert metadata["filter_rejections"]["too_short"] == 9


def test_pre_reranker_filter_rejects_consent_dominant_chunks() -> None:
    consent = " ".join(
        [
            "Manage your privacy. Accept all cookies. Consent preferences include "
            "advertising partners and legitimate interests."
        ]
        * 30
    )
    selected, metadata = _filter_for_reranking(
        "unrelated technical question",
        [_candidate(1, consent, 1, 1)],
        1,
    )
    assert selected == []
    assert metadata["filter_rejections"]["content_quality"] == 1


def test_equal_channel_scores_receive_equal_ranks() -> None:
    assert _rank_map({3: 0.5, 1: 0.5, 2: 0.4}) == {1: 1, 3: 1, 2: 3}


def test_packed_sources_include_clickable_markdown_hyperlinks() -> None:
    context, sources = _render_context(
        "question",
        "topic",
        [_candidate(1, "answer evidence", 1, 1).model_copy(update={"title": "Answer"})],
        "balanced",
    )
    assert "[Answer](https://s1.test)" in context
    assert sources[0]["citation"] == "[Answer](https://s1.test)"
    assert "BEGIN UNTRUSTED EVIDENCE SOURCE-1-CHUNK-1" in context
    assert "END UNTRUSTED EVIDENCE SOURCE-1-CHUNK-1" in context
    assert context.index("BEGIN UNTRUSTED EVIDENCE") < context.index("## Source 1")
