from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .chunking import chunk_text
from .clean import find_prompt_injection_markers, normalize_url
from .config import settings
from .context_budget import calculate_context_budget
from .context_packer import pack_context, select_chunks
from .embeddings import embedder
from .errors import SearchUnavailableError
from .freshness import freshness_window, query_needs_freshness
from .llama_discovery import runtime
from .logging_utils import log_extra
from .models import ContextChunk, IngestResult, PackedContext, SearchResult
from .research_controller import EvidenceAssessment, assess_evidence, initial_pass
from .retrieval import retrieve_and_rerank
from .retrieval_policy import (
    ResolvedResearchModeLimits,
    RetrievalLimits,
    calculate_context_retrieval_limits,
    calculate_research_pass_limits,
    evidence_checkpoints,
    resolve_research_mode_limits,
)
from .scrape import scrape_url
from .search import searxng_client_scope, web_search
from .security import safe_url_label
from .store import find_fresh_source, find_stale_source, reuse_stored_content, store_document

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchRequest:
    query: str
    topic: str
    freshness: str | None
    effective_freshness: str | None
    language: str
    requested_mode: str
    deadline: float


@dataclass(frozen=True)
class ResearchPassResult:
    pass_name: str
    limits: RetrievalLimits
    queries_planned: int
    search_results: int
    search_diagnostics: dict
    pages_attempted: int
    pages_ingested: int
    evidence_checks: int
    assessment: EvidenceAssessment

    def metadata(self) -> dict:
        return {
            "pass": self.pass_name,
            "page_attempt_limit": self.limits.max_page_attempts,
            "queries_planned": self.queries_planned,
            "search_results": self.search_results,
            "search": self.search_diagnostics,
            "new_pages_attempted": self.pages_attempted,
            "new_pages_ingested": self.pages_ingested,
            "evidence_checks": self.evidence_checks,
            "evidence": self.assessment.metadata(),
        }


@dataclass
class ResearchRunState:
    chunks: list[ContextChunk]
    assessment: EvidenceAssessment
    limits: RetrievalLimits
    reranker_metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    seen_urls: set[str] = field(default_factory=set)
    blocked_access_outcomes: dict[str, int] = field(default_factory=dict)
    passes: list[ResearchPassResult] = field(default_factory=list)


def plan_queries(query: str, count: int, freshness: str | None = None) -> list[str]:
    base = query.strip()
    variants = [base]
    if freshness in {"day", "month", "year"} and not query_needs_freshness(base, "auto"):
        variants.append(f"{base} latest")
    if re.search(r"\b(compare|comparison|versus|vs\.?|difference between)\b", base, re.I):
        variants.append(f"{base} comparison")
    clauses = [item.strip(" ?") for item in re.split(r"[;?]+", base) if len(item.split()) >= 3]
    if len(clauses) < 2 and " and " in base.casefold():
        clauses = [
            item.strip(" ?")
            for item in re.split(r"\band\b", base, flags=re.I)
            if len(item.split()) >= 3
        ]
    if len(clauses) > 1:
        variants.extend(clauses)
    return list(dict.fromkeys(item for item in variants if item))[:count]


async def search_many(
    query: str,
    max_queries: int,
    max_results: int,
    freshness: str | None,
    language: str,
) -> tuple[list[SearchResult], dict]:
    fused: dict[str, tuple[SearchResult, float, int]] = {}
    statuses: list[dict] = []
    planned_queries = plan_queries(query, max_queries, freshness)
    async with searxng_client_scope():
        for query_index, planned in enumerate(planned_queries):
            try:
                result_set = await web_search(
                    planned,
                    max_results=max_results,
                    freshness=freshness,
                    language=language,
                )
                statuses.append(
                    {
                        "query_index": query_index,
                        "status": "ok",
                        "result_count": len(result_set),
                    }
                )
                for rank, item in enumerate(result_set, 1):
                    previous = fused.get(item.url)
                    contribution = 1.0 / (60.0 + rank)
                    if previous is None:
                        fused[item.url] = (item, contribution, 1)
                    else:
                        best, total, matches = previous
                        if item.score > best.score:
                            best = item
                        fused[item.url] = (best, total + contribution, matches + 1)
            except Exception as exc:
                statuses.append(
                    {
                        "query_index": query_index,
                        "status": "failed",
                        "result_count": 0,
                        "error_type": type(exc).__name__,
                    }
                )
                log_extra(
                    logger,
                    logging.WARNING,
                    "search_query_failed",
                    query_index=query_index,
                    error=type(exc).__name__,
                )
    failed = sum(status["status"] == "failed" for status in statuses)
    if statuses and failed == len(statuses):
        raise SearchUnavailableError(
            "Every planned SearXNG query failed.",
            details={"queries_planned": len(statuses), "queries_failed": failed},
            resolution="Check the local SearXNG service with `ai-websearch doctor --search-probe`.",
        )
    ordered = sorted(
        (item.model_copy(update={"score": score}) for item, score, _matches in fused.values()),
        key=lambda item: (-item.score, item.url),
    )
    selected: list[SearchResult] = []
    per_domain: dict[str, int] = {}
    for item in ordered:
        domain = (urlsplit(item.url).hostname or "").casefold()
        if per_domain.get(domain, 0) >= 2:
            continue
        selected.append(item)
        per_domain[domain] = per_domain.get(domain, 0) + 1
        if len(selected) >= max_results:
            break
    diagnostics = {
        "queries_planned": len(statuses),
        "queries_succeeded": len(statuses) - failed,
        "queries_failed": failed,
        "partial_failure": 0 < failed < len(statuses),
        "queries": statuses,
    }
    return selected, diagnostics


async def ingest_url(
    url: str,
    topic: str | None = None,
    *,
    published_at_hint: str | None = None,
    published_at_hint_source: str | None = None,
) -> IngestResult:
    url = normalize_url(url)
    cached = find_fresh_source(url, topic, settings.cache_ttl_hours)
    if cached is not None:
        return cached
    page = await scrape_url(url)
    if not page.success:
        stale = find_stale_source(url, topic, refresh_outcome=page.outcome)
        if stale is not None:
            return stale.model_copy(update={"http_status": page.http_status})
        return IngestResult(
            ok=False,
            url=url,
            error=page.error,
            fetched_at=page.fetched_at,
            outcome=page.outcome,
            http_status=page.http_status,
        )
    effective_published_at = page.published_at or published_at_hint
    effective_published_at_source = (
        page.published_at_source
        if page.published_at
        else published_at_hint_source
        if published_at_hint
        else None
    )
    reused = reuse_stored_content(
        page.canonical_url or page.url,
        page.content_hash or "",
        topic,
        page.fetched_at,
        effective_published_at,
        effective_published_at_source,
    )
    if reused is not None:
        return reused.model_copy(update={"http_status": page.http_status})
    chunks = chunk_text(page.markdown)
    if not chunks:
        return IngestResult(
            ok=False,
            url=url,
            error="No chunks produced",
            fetched_at=page.fetched_at,
            http_status=page.http_status,
        )
    markers = find_prompt_injection_markers(page.markdown)
    try:
        vectors = await embedder.embed_texts(chunks)
        result = store_document(
            page.url,
            page.canonical_url,
            page.title,
            page.markdown,
            page.fetched_at,
            effective_published_at,
            topic,
            chunks,
            vectors,
            published_at_source=effective_published_at_source,
        )
        if markers:
            log_extra(
                logger,
                logging.WARNING,
                "prompt_injection_markers_detected",
                url_reference=safe_url_label(url),
                markers=markers,
            )
        return result.model_copy(update={"http_status": page.http_status})
    except Exception as exc:
        return IngestResult(
            ok=False,
            url=url,
            error=f"{type(exc).__name__}: ingestion failed safely",
            fetched_at=page.fetched_at,
            http_status=page.http_status,
        )


async def _refresh_evidence(
    request: ResearchRequest,
    state: ResearchRunState,
    limits: RetrievalLimits,
) -> None:
    state.chunks, state.reranker_metadata = await retrieve_and_rerank(
        request.query,
        request.topic,
        top_k=limits.retrieve_candidates,
        candidate_k=limits.retrieve_candidates,
        reranking_candidates=limits.rerank_candidates,
        freshness=request.freshness,
    )
    state.assessment = assess_evidence(
        request.query,
        select_chunks(state.chunks, limits),
    )


def _deadline_search_diagnostics(planned_queries: int) -> dict:
    return {
        "queries_planned": planned_queries,
        "queries_succeeded": 0,
        "queries_failed": 0,
        "partial_failure": False,
        "deadline_exceeded": True,
        "queries": [
            {
                "query_index": index,
                "status": "deadline_exceeded",
                "result_count": 0,
            }
            for index in range(planned_queries)
        ],
    }


async def _run_research_pass(
    request: ResearchRequest,
    resolved_limits: ResolvedResearchModeLimits,
    state: ResearchRunState,
    pass_mode: str,
) -> ResearchPassResult:
    remaining_page_attempts = max(
        0,
        resolved_limits.max_page_attempts - len(state.seen_urls),
    )
    limits = calculate_research_pass_limits(
        resolved_limits,
        pass_mode,
        remaining_page_attempts,
    )
    state.limits = limits
    planned_queries = plan_queries(
        request.query,
        limits.search_queries,
        request.effective_freshness,
    )
    results: list[SearchResult] = []
    search_diagnostics = {
        "queries_planned": 0,
        "queries_succeeded": 0,
        "queries_failed": 0,
        "partial_failure": False,
        "queries": [],
    }
    if limits.max_page_attempts > 0 and time.monotonic() < request.deadline:
        try:
            async with asyncio.timeout(max(0.0, request.deadline - time.monotonic())):
                results, search_diagnostics = await search_many(
                    request.query,
                    limits.search_queries,
                    limits.search_results,
                    request.effective_freshness,
                    request.language,
                )
            if search_diagnostics["partial_failure"]:
                state.warnings.append(
                    f"{search_diagnostics['queries_failed']} of "
                    f"{search_diagnostics['queries_planned']} planned searches failed; "
                    "partial results were used."
                )
        except TimeoutError:
            search_diagnostics = _deadline_search_diagnostics(len(planned_queries))
            state.warnings.append("The remaining research deadline expired during web search.")

    attempted = 0
    ingested = 0
    evidence_checks = 0
    last_evidence_check_at = -1
    pass_evidence_checkpoints = evidence_checkpoints(limits.max_page_attempts)
    unseen_results = [result for result in results if result.url not in state.seen_urls]
    for result in unseen_results[: limits.max_page_attempts]:
        if time.monotonic() >= request.deadline:
            break
        state.seen_urls.add(result.url)
        attempted += 1
        try:
            async with asyncio.timeout(max(0.0, request.deadline - time.monotonic())):
                ingest = await ingest_url(
                    result.url,
                    request.topic,
                    published_at_hint=result.published_at,
                    published_at_hint_source=result.published_at_source,
                )
        except TimeoutError:
            state.warnings.append("The remaining research deadline expired during page ingestion.")
            state.blocked_access_outcomes["deadline_exceeded"] = (
                state.blocked_access_outcomes.get("deadline_exceeded", 0) + 1
            )
            break
        if ingest.ok:
            ingested += 1
            if ingest.cache_status == "stale_fallback":
                state.warnings.append(
                    "Used previously cached evidence after a failed refresh "
                    f"({ingest.refresh_outcome or 'unknown'})."
                )
        else:
            state.warnings.append(f"Failed to ingest {safe_url_label(result.url)}: {ingest.error}")
            state.blocked_access_outcomes[ingest.outcome] = (
                state.blocked_access_outcomes.get(ingest.outcome, 0) + 1
            )
        if attempted in pass_evidence_checkpoints:
            await _refresh_evidence(request, state, limits)
            evidence_checks += 1
            last_evidence_check_at = attempted
            if state.assessment.sufficient:
                break
    if last_evidence_check_at != attempted:
        await _refresh_evidence(request, state, limits)
        evidence_checks += 1
    pass_result = ResearchPassResult(
        pass_name=pass_mode,
        limits=limits,
        queries_planned=len(planned_queries),
        search_results=len(results),
        search_diagnostics=search_diagnostics,
        pages_attempted=attempted,
        pages_ingested=ingested,
        evidence_checks=evidence_checks,
        assessment=state.assessment,
    )
    state.passes.append(pass_result)
    return pass_result


async def research(
    query: str,
    topic: str | None = None,
    freshness: str | None = "auto",
    language: str = "en",
    context_mode: str | None = None,
    context_budget_tokens: int | None = None,
    max_page_attempts: int | None = None,
    max_sources: int | None = None,
    max_chunks: int | None = None,
    mode: str | None = None,
) -> PackedContext:
    server = await runtime.get()
    budget = calculate_context_budget(server.context_tokens, context_budget_tokens)
    packing_mode = context_mode or settings.default_context_mode
    requested_mode = (mode or settings.default_research_mode).casefold().strip()
    resolved_limits = resolve_research_mode_limits(
        budget.applied_web_tokens,
        requested_mode,
        requested_max_page_attempts=max_page_attempts,
        requested_max_sources=max_sources,
        requested_max_chunks=max_chunks,
    )
    current_pass = initial_pass(requested_mode)
    chosen_topic = topic or query[:80]
    effective_freshness = freshness_window(query, freshness)
    started = time.monotonic()
    deadline_seconds = (
        settings.rapid_research_max_seconds
        if requested_mode == "rapid"
        else settings.deep_research_max_seconds
    )
    deadline = started + deadline_seconds
    initial_limits = calculate_research_pass_limits(
        resolved_limits,
        current_pass,
        resolved_limits.max_page_attempts,
    )
    request = ResearchRequest(
        query=query,
        topic=chosen_topic,
        freshness=freshness,
        effective_freshness=effective_freshness,
        language=language,
        requested_mode=requested_mode,
        deadline=deadline,
    )
    state = ResearchRunState(
        chunks=[],
        assessment=assess_evidence(query, []),
        limits=initial_limits,
    )
    await _run_research_pass(request, resolved_limits, state, current_pass)
    escalated = False
    escalation_reason: str | None = None
    if (
        requested_mode == "auto"
        and current_pass == "rapid"
        and not state.assessment.sufficient
        and time.monotonic() < deadline
        and len(state.seen_urls) < resolved_limits.max_page_attempts
    ):
        escalated = True
        escalation_reason = state.assessment.reason
        current_pass = "deep"
        await _run_research_pass(request, resolved_limits, state, current_pass)

    if state.assessment.sufficient:
        stop_reason = "sufficient_evidence"
    elif time.monotonic() >= deadline:
        stop_reason = "time_budget_reached"
    elif len(state.seen_urls) >= resolved_limits.max_page_attempts:
        stop_reason = "page_attempt_budget_reached"
    elif len(state.passes) > 1 and state.passes[-1].pages_ingested == 0:
        stop_reason = "no_new_evidence"
    else:
        stop_reason = state.assessment.reason
    research_metadata = {
        "mode_requested": requested_mode,
        "mode_used": current_pass,
        "escalated": escalated,
        "escalation_reason": escalation_reason,
        "stop_reason": stop_reason,
        "evidence_assessment": state.assessment.metadata(),
        "limits": resolved_limits.metadata(),
        "passes": [result.metadata() for result in state.passes],
        "unique_urls_considered": len(state.seen_urls),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "time_budget_seconds": deadline_seconds,
        "blocked_access_outcomes": state.blocked_access_outcomes,
        "answerability": {
            "answerable": state.assessment.sufficient,
            "required_action": (
                "answer_with_citations"
                if state.assessment.sufficient
                else "state_insufficient_evidence"
            ),
        },
    }
    return await pack_context(
        query,
        chosen_topic,
        state.chunks,
        server,
        budget,
        state.limits,
        packing_mode,
        state.warnings,
        state.reranker_metadata,
        research_metadata,
    )


async def retrieve_context(
    query: str,
    topic: str | None = None,
    context_mode: str | None = None,
    context_budget_tokens: int | None = None,
    top_k: int | None = None,
    max_sources: int | None = None,
    max_chunks: int | None = None,
) -> PackedContext:
    server = await runtime.get()
    budget = calculate_context_budget(server.context_tokens, context_budget_tokens)
    mode = context_mode or settings.default_context_mode
    limits = calculate_context_retrieval_limits(
        budget.applied_web_tokens,
        top_k=top_k,
        requested_max_sources=max_sources,
        requested_max_chunks=max_chunks,
    )
    chunks, reranker_metadata = await retrieve_and_rerank(
        query,
        topic,
        top_k=limits.retrieve_candidates,
        candidate_k=limits.retrieve_candidates,
        reranking_candidates=limits.rerank_candidates,
    )

    return await pack_context(
        query, topic, chunks, server, budget, limits, mode, reranker_metadata=reranker_metadata
    )
