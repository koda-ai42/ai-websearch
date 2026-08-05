from __future__ import annotations

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class ResearchPassLimits:
    """Search and crawl work attached to one controller pass."""

    name: str
    search_queries: int
    search_results: int
    max_page_attempts: int
    retrieve_candidates: int
    max_chunks_per_source: int


RAPID_PASS_LIMITS = ResearchPassLimits("rapid", 1, 5, 2, 48, 4)
DEEP_PASS_LIMITS = ResearchPassLimits("deep", 5, 20, 10, 300, 8)


@dataclass(frozen=True)
class ResearchModeDefaults:
    mode: str
    max_page_attempts: int
    max_sources: int
    max_chunks: int

    def metadata(self) -> dict[str, int]:
        return {
            "max_page_attempts": self.max_page_attempts,
            "max_sources": self.max_sources,
            "max_chunks": self.max_chunks,
        }


RESEARCH_MODE_DEFAULTS = {
    "rapid": ResearchModeDefaults("rapid", 2, 2, 8),
    "auto": ResearchModeDefaults("auto", 5, 5, 15),
    "deep": ResearchModeDefaults("deep", 10, 8, 24),
}


@dataclass(frozen=True)
class ResolvedResearchModeLimits:
    mode: str
    mode_defaults: ResearchModeDefaults
    requested_max_page_attempts: int | None
    requested_max_sources: int | None
    requested_max_chunks: int | None
    max_page_attempts: int
    max_sources: int
    max_chunks: int
    hard_max_page_attempts: int

    def requested_metadata(self) -> dict[str, int]:
        requested = {
            "max_page_attempts": self.requested_max_page_attempts,
            "max_sources": self.requested_max_sources,
            "max_chunks": self.requested_max_chunks,
        }
        return {key: value for key, value in requested.items() if value is not None}

    def effective_metadata(self) -> dict[str, int]:
        return {
            "max_page_attempts": self.max_page_attempts,
            "max_sources": self.max_sources,
            "max_chunks": self.max_chunks,
        }

    def metadata(self) -> dict:
        return {
            "mode_defaults": self.mode_defaults.metadata(),
            "requested": self.requested_metadata(),
            "effective": self.effective_metadata(),
            "absolute_max_page_attempts": self.hard_max_page_attempts,
        }


@dataclass(frozen=True)
class RetrievalLimits:
    name: str
    search_queries: int
    search_results: int
    max_page_attempts: int
    max_chunks: int
    max_sources: int
    retrieve_candidates: int
    rerank_candidates: int
    max_chunks_per_source: int


def _validate_optional_positive(name: str, value: int | None) -> int | None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def evidence_checkpoints(max_page_attempts: int) -> tuple[int, ...]:
    """Return bounded crawl-wave endpoints for evidence reassessment."""

    if max_page_attempts < 0:
        raise ValueError("max_page_attempts cannot be negative")
    return tuple(
        sorted(
            {
                min(checkpoint, max_page_attempts)
                for checkpoint in (2, 5, max_page_attempts)
                if max_page_attempts > 0
            }
        )
    )


def _bounded_chunks(budget_tokens: int, default: int, requested: int | None) -> int:
    budget_chunk_limit = max(4, budget_tokens // 700)
    max_chunks = min(default, budget_chunk_limit)
    if requested is not None:
        max_chunks = min(max_chunks, requested)
    if settings.reranking_mode == "cross_encoder":
        max_chunks = min(max_chunks, settings.reranking_candidates)
    return max_chunks


def _bounded_sources(default: int, max_chunks: int, requested: int | None) -> int:
    chunk_supported_sources = max(1, (max_chunks + 2) // 3)
    max_sources = min(default, chunk_supported_sources)
    if requested is not None:
        max_sources = min(max_sources, requested)
    return max_sources


def resolve_research_mode_limits(
    budget_tokens: int,
    mode: str,
    *,
    requested_max_page_attempts: int | None = None,
    requested_max_sources: int | None = None,
    requested_max_chunks: int | None = None,
) -> ResolvedResearchModeLimits:
    normalized_mode = mode.casefold().strip()
    if normalized_mode not in RESEARCH_MODE_DEFAULTS:
        raise ValueError("mode must be rapid, deep, or auto")
    requested_max_page_attempts = _validate_optional_positive(
        "max_page_attempts", requested_max_page_attempts
    )
    requested_max_sources = _validate_optional_positive("max_sources", requested_max_sources)
    requested_max_chunks = _validate_optional_positive("max_chunks", requested_max_chunks)

    defaults = RESEARCH_MODE_DEFAULTS[normalized_mode]
    hard_page_limit = settings.research_max_page_attempts_hard_limit
    max_page_attempts = min(defaults.max_page_attempts, hard_page_limit)
    if requested_max_page_attempts is not None:
        max_page_attempts = min(max_page_attempts, requested_max_page_attempts)
    max_chunks = _bounded_chunks(budget_tokens, defaults.max_chunks, requested_max_chunks)
    max_sources = _bounded_sources(defaults.max_sources, max_chunks, requested_max_sources)
    return ResolvedResearchModeLimits(
        mode=defaults.mode,
        mode_defaults=defaults,
        requested_max_page_attempts=requested_max_page_attempts,
        requested_max_sources=requested_max_sources,
        requested_max_chunks=requested_max_chunks,
        max_page_attempts=max_page_attempts,
        max_sources=max_sources,
        max_chunks=max_chunks,
        hard_max_page_attempts=hard_page_limit,
    )


def calculate_research_pass_limits(
    resolved: ResolvedResearchModeLimits,
    pass_name: str,
    remaining_page_attempts: int,
) -> RetrievalLimits:
    if remaining_page_attempts < 0:
        raise ValueError("remaining_page_attempts cannot be negative")
    normalized_pass = pass_name.casefold().strip()
    if normalized_pass == "rapid":
        pass_limits = RAPID_PASS_LIMITS
    elif normalized_pass == "deep":
        pass_limits = DEEP_PASS_LIMITS
    else:
        raise ValueError("pass_name must be rapid or deep")
    pass_page_attempts = pass_limits.max_page_attempts
    if resolved.mode == "auto" and normalized_pass == "deep":
        auto_escalation_ceiling = (
            RESEARCH_MODE_DEFAULTS["auto"].max_page_attempts - RAPID_PASS_LIMITS.max_page_attempts
        )
        pass_page_attempts = min(pass_page_attempts, auto_escalation_ceiling)
    retrieve_candidates = min(pass_limits.retrieve_candidates, resolved.max_chunks * 6)
    rerank_candidates = (
        min(settings.reranking_candidates, retrieve_candidates)
        if settings.reranking_mode == "cross_encoder"
        else retrieve_candidates
    )
    return RetrievalLimits(
        name=pass_limits.name,
        search_queries=pass_limits.search_queries,
        search_results=pass_limits.search_results,
        max_page_attempts=min(pass_page_attempts, remaining_page_attempts),
        max_chunks=resolved.max_chunks,
        max_sources=resolved.max_sources,
        retrieve_candidates=retrieve_candidates,
        rerank_candidates=rerank_candidates,
        max_chunks_per_source=pass_limits.max_chunks_per_source,
    )


def calculate_context_retrieval_limits(
    budget_tokens: int,
    *,
    top_k: int | None = None,
    requested_max_sources: int | None = None,
    requested_max_chunks: int | None = None,
) -> RetrievalLimits:
    top_k = _validate_optional_positive("top_k", top_k)
    requested_max_sources = _validate_optional_positive("max_sources", requested_max_sources)
    requested_max_chunks = _validate_optional_positive("max_chunks", requested_max_chunks)
    max_chunks = _bounded_chunks(budget_tokens, 24, requested_max_chunks)
    if top_k is not None:
        max_chunks = min(max_chunks, top_k)
    max_sources = _bounded_sources(8, max_chunks, requested_max_sources)
    retrieve_candidates = top_k if top_k is not None else min(150, max_chunks * 6)
    rerank_candidates = (
        min(settings.reranking_candidates, retrieve_candidates)
        if settings.reranking_mode == "cross_encoder"
        else retrieve_candidates
    )
    return RetrievalLimits(
        name="context",
        search_queries=0,
        search_results=0,
        max_page_attempts=0,
        max_chunks=max_chunks,
        max_sources=max_sources,
        retrieve_candidates=retrieve_candidates,
        rerank_candidates=rerank_candidates,
        max_chunks_per_source=3,
    )
