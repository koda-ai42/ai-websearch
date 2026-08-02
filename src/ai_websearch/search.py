from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

import httpx

from .clean import normalize_url
from .config import settings
from .freshness import normalize_publication_date
from .logging_utils import log_extra
from .models import SearchResult
from .network_policy import DomainRateLimiter
from .url_policy import check_url

logger = logging.getLogger(__name__)
_search_limiter = DomainRateLimiter(
    settings.search_concurrency,
    settings.search_min_interval_seconds,
)

_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_scoped_client: ContextVar[httpx.AsyncClient | None] = ContextVar(
    "ai_websearch_searxng_client",
    default=None,
)


@asynccontextmanager
async def searxng_client_scope():
    existing = _scoped_client.get()
    if existing is not None:
        yield existing
        return
    async with httpx.AsyncClient(
        timeout=settings.searxng_timeout_seconds,
        follow_redirects=False,
    ) as client:
        token = _scoped_client.set(client)
        try:
            yield client
        finally:
            _scoped_client.reset(token)


def _retryable_search_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return False


async def web_search(
    query: str, max_results: int = 8, freshness: str | None = None, language: str = "en"
) -> list[SearchResult]:
    if _scoped_client.get() is None:
        async with searxng_client_scope():
            return await web_search(query, max_results, freshness, language)
    max_results = max(1, min(max_results, 50))
    params = {"q": query, "format": "json", "language": language, "safesearch": 1}
    if freshness in {"day", "month", "year"}:
        params["time_range"] = freshness
    endpoint = settings.searxng_url.rstrip("/") + "/search"
    data = None
    for attempt in range(settings.max_retries):
        try:
            async with _search_limiter.acquire(endpoint):
                client = _scoped_client.get()
                if client is None:  # pragma: no cover - established by the wrapper above
                    raise RuntimeError("SearXNG client scope was not initialized")
                try:
                    response = await client.get(endpoint, params=params)
                finally:
                    client.cookies.clear()
                response.raise_for_status()
                data = response.json()
            break
        except Exception as exc:
            log_extra(
                logger,
                logging.WARNING,
                "searxng_search_failed",
                query_length=len(query),
                attempt=attempt + 1,
                error=type(exc).__name__,
            )
            if not _retryable_search_error(exc) or attempt + 1 >= settings.max_retries:
                raise RuntimeError("SearXNG remained unavailable after bounded retries.") from exc
            await asyncio.sleep(settings.retry_backoff_seconds * (attempt + 1))

    results: list[SearchResult] = []
    seen: set[str] = set()
    for item in (data or {}).get("results", []):
        raw_url = item.get("url") or ""
        if not raw_url:
            continue
        normalized = normalize_url(raw_url)
        if normalized in seen:
            continue
        seen.add(normalized)
        title, content = item.get("title") or "", item.get("content") or ""
        if not check_url(normalized).allowed:
            continue
        raw_engines = item.get("engines")
        engines = [str(value) for value in raw_engines] if isinstance(raw_engines, list) else []
        engine = item.get("engine")
        if isinstance(engine, str) and engine and engine not in engines:
            engines.append(engine)
        published_at = normalize_publication_date(
            str(item.get("publishedDate")) if item.get("publishedDate") else None,
            datetime.now(timezone.utc).isoformat(),
        )
        results.append(
            SearchResult(
                title=title,
                url=normalized,
                content=content,
                engine=engine if isinstance(engine, str) else None,
                engines=engines,
                score=float(item.get("score") or 0.0),
                published_at=published_at,
                published_at_source="search_result" if published_at else None,
            )
        )
        if len(results) >= max_results:
            break
    return sorted(results, key=lambda result: result.score, reverse=True)
