from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from .config import settings
from .errors import AiWebsearchError
from .integration_contract import ANSWER_AGENT_INSTRUCTIONS
from .llama_discovery import runtime
from .logging_utils import setup_logging
from .orchestrator import (
    ingest_url as orchestrator_ingest_url,
)
from .orchestrator import (
    research as orchestrator_research,
)
from .orchestrator import (
    retrieve_context as orchestrator_retrieve_context,
)
from .reranking import reranker
from .scrape import scrape_url as scrape_one_url
from .search import web_search as searxng_web_search
from .store import (
    delete_source as store_delete_source,
)
from .store import (
    initialize_database,
)
from .store import (
    list_sources as store_list_sources,
)
from .url_policy import check_urls

ResearchMode = Annotated[
    Literal["rapid", "deep", "auto"],
    Field(
        description="Research progression: one rapid pass, one deep pass, or rapid then one optional deep pass."
    ),
]
PageAttemptLimit = Annotated[
    int | None,
    Field(
        ge=1,
        description="Optional request-wide URL-attempt ceiling; can only tighten the selected mode default.",
    ),
]
SourceLimit = Annotated[
    int | None,
    Field(
        ge=1, description="Optional packed-source ceiling; can only tighten the applicable default."
    ),
]
ChunkLimit = Annotated[
    int | None,
    Field(
        ge=1, description="Optional packed-chunk ceiling; can only tighten the applicable default."
    ),
]
RetrievalCandidateLimit = Annotated[
    int | None,
    Field(ge=1, description="Optional first-stage retrieval-candidate ceiling."),
]


def _error(exc: Exception) -> dict:
    return (
        exc.to_dict()
        if isinstance(exc, AiWebsearchError)
        else {
            "error": "operation_failed",
            "message": "The operation failed without exposing internal paths or credentials.",
            "details": {"error_type": type(exc).__name__},
        }
    )


async def web_search(
    query: str, max_results: int = 8, freshness: str | None = None, language: str = "en"
) -> list[dict[str, Any]] | dict:
    """Diagnostic raw search; answer agents should use research instead."""
    try:
        return [
            item.model_dump()
            for item in await searxng_web_search(query, max_results, freshness, language)
        ]
    except Exception as exc:
        return _error(exc)


async def scrape_url(url: str) -> dict[str, Any]:
    """Diagnostic one-page scrape; answer agents should use research instead."""
    return (await scrape_one_url(url)).model_dump()


async def ingest_url(url: str, topic: str | None = None) -> dict[str, Any]:
    """Administrative ingestion; answer agents should use research instead."""
    return (await orchestrator_ingest_url(url, topic)).model_dump()


async def research(
    query: str,
    topic: str | None = None,
    freshness: str | None = None,
    language: str = "en",
    context_mode: str = "balanced",
    context_budget_tokens: int | None = None,
    max_page_attempts: PageAttemptLimit = None,
    max_sources: SourceLimit = None,
    max_chunks: ChunkLimit = None,
    mode: ResearchMode = "auto",
) -> dict[str, Any]:
    """Run one bounded aggregate web-research workflow.

    Mode selects rapid, deep, or one-step automatic escalation. Optional numeric
    limits can only tighten that mode's request-wide page, source, and chunk
    ceilings. Use this tool instead of composing low-level search and crawl calls.
    """
    try:
        result = await orchestrator_research(
            query=query,
            topic=topic,
            freshness=freshness,
            language=language,
            context_mode=context_mode,
            context_budget_tokens=context_budget_tokens,
            max_page_attempts=max_page_attempts,
            max_sources=max_sources,
            max_chunks=max_chunks,
            mode=mode,
        )
        return result.model_dump()
    except Exception as exc:
        return _error(exc)


async def retrieve_context(
    query: str,
    topic: str | None = None,
    context_mode: str = "balanced",
    context_budget_tokens: int | None = None,
    top_k: RetrievalCandidateLimit = None,
    max_sources: SourceLimit = None,
    max_chunks: ChunkLimit = None,
) -> dict[str, Any]:
    """Retrieve already-ingested evidence without searching or crawling.

    top_k bounds first-stage retrieval candidates; max_sources and max_chunks
    bound the final packed evidence.
    """
    try:
        result = await orchestrator_retrieve_context(
            query=query,
            topic=topic,
            context_mode=context_mode,
            context_budget_tokens=context_budget_tokens,
            top_k=top_k,
            max_sources=max_sources,
            max_chunks=max_chunks,
        )
        return result.model_dump()
    except Exception as exc:
        return _error(exc)


async def score_sources(urls: list[str]) -> list[dict[str, Any]] | dict:
    try:
        return check_urls(urls)
    except Exception as exc:
        return _error(exc)


async def list_sources(
    topic: str | None = None, limit: int = 50, min_score: float = 0.0
) -> list[dict[str, Any]]:
    return store_list_sources(topic, limit, min_score)


async def delete_source(source_id: int) -> dict[str, Any]:
    return {"source_id": source_id, "deleted": store_delete_source(source_id)}


TOOLS = {
    "web_search": web_search,
    "scrape_url": scrape_url,
    "ingest_url": ingest_url,
    "research": research,
    "retrieve_context": retrieve_context,
    "score_sources": score_sources,
    "list_sources": list_sources,
    "delete_source": delete_source,
}
TOOLSETS = {
    "answer": ("research",),
    "diagnostic": (
        "research",
        "web_search",
        "scrape_url",
        "retrieve_context",
        "score_sources",
        "list_sources",
    ),
    "admin": tuple(TOOLS),
}


def create_mcp(toolset: str = "answer") -> FastMCP:
    if toolset not in TOOLSETS:
        raise ValueError("MCP toolset must be answer, diagnostic, or admin")
    application = FastMCP(
        "ai-websearch",
        instructions=ANSWER_AGENT_INSTRUCTIONS,
    )
    for name in TOOLSETS[toolset]:
        application.tool(TOOLS[name])
    return application


mcp = create_mcp(settings.mcp_toolset)


def main(toolset: str | None = None) -> None:
    setup_logging()
    try:
        server = asyncio.run(runtime.initialize())
        asyncio.run(reranker.initialize())
        initialize_database()
        print({"event": "llama_cpp_detected", **server.metadata()})
    except Exception as exc:
        print(_error(exc))
        raise SystemExit(1) from exc
    application = create_mcp(toolset or settings.mcp_toolset)
    try:
        application.run(
            transport="http",
            host=settings.mcp_host,
            port=settings.mcp_port,
            show_banner=False,
        )
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
