from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .access_outcomes import classify_access_outcome
from .clean import content_hash, normalize_url, strip_page_boilerplate
from .config import settings
from .content_quality import assess_content_quality
from .freshness import normalize_publication_date
from .logging_utils import log_extra
from .models import ScrapedPage
from .network_policy import DomainRateLimiter
from .url_policy import check_url, check_url_network

logger = logging.getLogger(__name__)


def _apply_truncation_limit(markdown: str, max_chars: int) -> str:
    """Apply soft truncation limit.  value of 0 means no limit."""
    if max_chars > 0 and len(markdown) > max_chars:
        logger.warning("page exceeds %d chars, truncating", max_chars)
        return markdown[:max_chars]
    return markdown
_crawl_limiter = DomainRateLimiter(
    settings.crawl_domain_concurrency,
    settings.crawl_min_interval_seconds,
)

_RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_RETRYABLE_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "net::err_",
    "temporarily unavailable",
)


class RetryableCrawlError(RuntimeError):
    def __init__(self, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


def _http_status(result: object) -> int | None:
    status = getattr(result, "status_code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def _retryable_crawl_error(exc: Exception) -> bool:
    return isinstance(exc, (RetryableCrawlError, TimeoutError, ConnectionError))


def _crawl_result_outcome(
    result: object,
    title: str,
    html: str | None,
    markdown: str,
) -> str:
    headers = getattr(result, "response_headers", None) or {}
    normalized_headers = {str(key).casefold(): str(value) for key, value in headers.items()}
    if "robots.txt" in normalized_headers.get("x-robots-status", "").casefold():
        return "robots_denied"

    status = _http_status(result)
    if status in _RETRYABLE_HTTP_STATUS_CODES:
        raise RetryableCrawlError(f"transient HTTP status {status}", http_status=status)

    if not (html or "").strip() and not markdown.strip():
        if bool(getattr(result, "success", False)):
            return "empty_content"
        message = str(getattr(result, "error_message", None) or "").casefold()
        if any(marker in message for marker in _RETRYABLE_ERROR_MARKERS):
            raise RetryableCrawlError("transient crawler failure")
        if status == 401 or status == 407:
            return "authentication"
        if status == 402:
            return "subscription"
        if isinstance(status, int) and status >= 400:
            return "access_denied" if status in {403, 451} else "http_error"
        return "extraction_failure"

    classified = classify_access_outcome(title, html, markdown)
    if classified != "success":
        return classified
    if status == 401 or status == 407:
        return "authentication"
    if status == 402:
        return "subscription"
    if isinstance(status, int) and status >= 400:
        return "access_denied" if status in {403, 451} else "http_error"
    if not bool(getattr(result, "success", False)):
        message = str(getattr(result, "error_message", None) or "").casefold()
        if any(marker in message for marker in _RETRYABLE_ERROR_MARKERS):
            raise RetryableCrawlError("transient crawler failure")
        return "extraction_failure"
    return "success"


def _markdown_from_result(result: object) -> str:
    value = getattr(result, "markdown", None)
    if isinstance(value, str):
        return value
    if value is not None:
        for attribute in ("raw_markdown", "markdown_with_citations", "fit_markdown"):
            candidate = getattr(value, attribute, None)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
    return ""


def _title(result: object, html: str | None, markdown: str) -> str:
    direct = getattr(result, "title", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()[:250]
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict) and isinstance(metadata.get("title"), str):
        return metadata["title"].strip()[:250]
    for line in markdown.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:252]
    if html:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()[:250]
    return ""


def _canonical_candidate(html: str | None, fallback: str) -> str:
    if html:
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("link", rel=lambda value: value and "canonical" in value)
        if link and link.get("href"):
            candidate = normalize_url(urljoin(fallback, str(link["href"])))
            if check_url(candidate).allowed:
                return candidate
    return normalize_url(fallback)


async def _canonical(html: str | None, fallback: str) -> str:
    candidate = _canonical_candidate(html, fallback)
    if candidate == normalize_url(fallback):
        return candidate
    policy = await check_url_network(candidate)
    return candidate if policy.allowed else normalize_url(fallback)


def _json_ld_dates(value: object) -> list[str]:
    if isinstance(value, list):
        return [date for item in value for date in _json_ld_dates(item)]
    if not isinstance(value, dict):
        return []
    dates = [str(value[key]) for key in ("datePublished", "dateCreated") if value.get(key)]
    return dates + [date for item in value.values() for date in _json_ld_dates(item)]


def _published(html: str | None, fetched_at: str) -> tuple[str | None, str | None]:
    if not html:
        return None, None
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text() or "")
        except (TypeError, json.JSONDecodeError):
            continue
        for value in _json_ld_dates(payload):
            normalized = normalize_publication_date(value, fetched_at)
            if normalized:
                return normalized, "json_ld"
    for attrs in (
        {"property": "article:published_time"},
        {"name": "date"},
        {"itemprop": "datePublished"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            normalized = normalize_publication_date(str(tag["content"])[:80], fetched_at)
            if normalized:
                return normalized, "meta"
    tag = soup.find("time")
    if tag:
        normalized = normalize_publication_date(
            str(tag.get("datetime") or tag.text).strip()[:80], fetched_at
        )
        if normalized:
            return normalized, "time"
    return None, None


async def _install_network_guard(page, **_kwargs) -> None:
    decisions: dict[str, bool] = {}

    async def guard(route) -> None:
        request_url = route.request.url
        scheme = urlsplit(request_url).scheme.casefold()
        if scheme in {"about", "blob", "data"}:
            await route.continue_()
            return
        key = request_url.split("/", 3)[2].casefold() if "://" in request_url else request_url
        allowed = decisions.get(key)
        if allowed is None:
            parsed = urlsplit(request_url)
            policy_url = urlunsplit(parsed._replace(query="", fragment=""))
            allowed = (await check_url_network(policy_url)).allowed
            decisions[key] = allowed
        if allowed:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    await page.route("**/*", guard)


async def _scrape_once(url: str, max_chars: int) -> ScrapedPage:
    from crawl4ai import AsyncWebCrawler

    try:
        from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError:
        from crawl4ai import BrowserConfig, CacheMode, CrawlerRunConfig

    fetched_at = datetime.now(timezone.utc).isoformat()
    browser_config = BrowserConfig(
        headless=True,
        browser_mode="dedicated",
        use_managed_browser=False,
        use_persistent_context=False,
        user_data_dir=None,
        storage_state=None,
        accept_downloads=False,
        ignore_https_errors=False,
        verbose=False,
        user_agent=settings.user_agent,
    )
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        verbose=False,
        check_robots_txt=True,
        word_count_threshold=10,
        remove_overlay_elements=True,
        excluded_tags=["script", "style", "noscript", "iframe"],
        page_timeout=int(settings.scrape_timeout_seconds * 1000),
    )
    with tempfile.TemporaryDirectory(prefix="ai-websearch-crawl-") as crawl_dir:
        async with AsyncWebCrawler(config=browser_config, base_directory=crawl_dir) as crawler:
            crawler.crawler_strategy.set_hook("on_page_context_created", _install_network_guard)
            result = await crawler.arun(url=url, config=run_config)

    html = getattr(result, "html", None)
    raw_markdown = _markdown_from_result(result)
    title = _title(result, html, raw_markdown)
    http_status = _http_status(result)
    outcome = _crawl_result_outcome(result, title, html, raw_markdown)
    if outcome != "success":
        return ScrapedPage(
            url=url,
            canonical_url=url,
            fetched_at=fetched_at,
            success=False,
            outcome=outcome,
            http_status=http_status,
            error=f"crawl access outcome: {outcome}",
        )
    final_url = normalize_url(str(getattr(result, "url", None) or url))
    final_policy = await check_url_network(final_url)
    if not final_policy.allowed:
        raise RuntimeError("Crawler redirect was blocked by URL policy")
    markdown = _apply_truncation_limit(strip_page_boilerplate(raw_markdown), max_chars)
    if not markdown:
        raise RuntimeError("Scrape succeeded but produced empty Markdown")
    quality = assess_content_quality(title, markdown)
    if not quality.usable:
        return ScrapedPage(
            url=final_url,
            canonical_url=await _canonical(html, final_url),
            title=title,
            fetched_at=fetched_at,
            success=False,
            outcome=quality.outcome,
            http_status=http_status,
            error=f"crawl content outcome: {quality.reason}",
        )
    published_at, published_at_source = _published(html, fetched_at)
    return ScrapedPage(
        url=final_url,
        canonical_url=await _canonical(html, final_url),
        title=title,
        markdown=markdown,
        fetched_at=fetched_at,
        published_at=published_at,
        published_at_source=published_at_source,
        content_hash=content_hash(markdown),
        http_status=http_status,
        success=True,
        outcome="success",
    )


async def scrape_url(
    url: str,
    max_chars: int | None = None,
) -> ScrapedPage:
    url = normalize_url(url)
    max_chars = max_chars or settings.max_chars_per_page
    fetched_at = datetime.now(timezone.utc).isoformat()
    policy = await check_url_network(url)
    if not policy.allowed:
        return ScrapedPage(
            url=url,
            canonical_url=url,
            fetched_at=fetched_at,
            success=False,
            outcome="access_denied",
            error=policy.reason,
        )

    last_error: Exception | None = None
    for attempt in range(settings.max_retries):
        try:
            async with _crawl_limiter.acquire(url):
                page = await _scrape_once(url, max_chars)
            # Access walls are deterministic and must never be retried or cached as content.
            if page.outcome != "success":
                return page
            return page
        except Exception as exc:
            last_error = exc
            log_extra(
                logger,
                logging.WARNING,
                "scrape_failed",
                domain=(urlsplit(url).hostname or ""),
                attempt=attempt + 1,
                error=type(exc).__name__,
            )
            if _retryable_crawl_error(exc) and attempt + 1 < settings.max_retries:
                await asyncio.sleep(settings.retry_backoff_seconds * (attempt + 1))
            else:
                break
    return ScrapedPage(
        url=url,
        canonical_url=url,
        fetched_at=fetched_at,
        success=False,
        outcome="extraction_failure",
        http_status=getattr(last_error, "http_status", None),
        error=f"{type(last_error).__name__}: crawl failed after bounded retries",
    )
