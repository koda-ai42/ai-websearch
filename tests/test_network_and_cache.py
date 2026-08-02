from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ai_websearch import orchestrator, store
from ai_websearch.access_outcomes import classify_access_outcome
from ai_websearch.config import settings
from ai_websearch.models import IngestResult, ScrapedPage
from ai_websearch.network_policy import DomainRateLimiter
from ai_websearch.scrape import (
    RetryableCrawlError,
    _canonical,
    _canonical_candidate,
    _crawl_result_outcome,
    _http_status,
    _retryable_crawl_error,
)
from ai_websearch.url_policy import UrlPolicyResult


def test_access_outcomes_are_distinct_and_article_cookie_footer_is_not_a_wall() -> None:
    assert classify_access_outcome("Verify", "<p>Verify you are human</p>", "") == "captcha"
    assert classify_access_outcome("Login", None, "Sign in to continue") == "authentication"
    assert classify_access_outcome("Premium", None, "Subscribe to continue") == "subscription"
    assert classify_access_outcome("Forbidden", None, "403 Forbidden") == "access_denied"
    assert (
        classify_access_outcome("Privacy", None, "Before you continue, accept all cookies")
        == "cookie_consent"
    )
    article = "useful public article evidence " * 500 + " accept all cookies"
    assert classify_access_outcome("Article", None, article) == "success"
    captcha_article = "A technical history of CAPTCHA systems and accessibility research. " * 100
    assert classify_access_outcome("CAPTCHA research", None, captcha_article) == "success"


def test_long_articles_quoting_wall_messages_are_not_access_walls() -> None:
    cases = [
        ("Authentication research", "Sign in to continue and authentication required"),
        ("CAPTCHA accessibility", "Verify that you are human and complete the captcha"),
        ("CDN incident report", "Checking if the site connection is secure. Cloudflare Ray ID"),
        ("Subscription economics", "Subscribe to continue and subscribers only"),
        ("HTTP authorization guide", "403 Forbidden and access denied"),
    ]
    for title, quoted_message in cases:
        article = (
            f"This public technical article discusses {quoted_message}. "
            "It documents methods, measurements, examples, limitations, and conclusions. "
        ) * 60
        assert classify_access_outcome(title, None, article) == "success"


def test_structural_wall_markers_classify_rendered_pages() -> None:
    assert (
        classify_access_outcome(
            "Please wait",
            '<main id="captcha-challenge"><form class="challenge-form"></form></main>',
            "",
        )
        == "captcha"
    )


def test_crawl_result_statuses_and_robots_are_first_class() -> None:
    robots = SimpleNamespace(
        response_headers={"X-Robots-Status": "Blocked by robots.txt"},
        status_code=403,
        success=False,
        error_message="Access denied by robots.txt",
    )
    assert _crawl_result_outcome(robots, "", None, "") == "robots_denied"

    unauthorized = SimpleNamespace(
        response_headers={}, status_code=401, success=False, error_message=""
    )
    assert _crawl_result_outcome(unauthorized, "", None, "login") == "authentication"

    missing = SimpleNamespace(
        response_headers={}, status_code=404, success=False, error_message="not found"
    )
    assert _crawl_result_outcome(missing, "Not found", None, "No article") == "http_error"

    empty = SimpleNamespace(response_headers={}, status_code=200, success=True, error_message="")
    assert _crawl_result_outcome(empty, "", None, "") == "empty_content"
    assert _http_status(empty) == 200
    assert _http_status(SimpleNamespace(status_code="200")) is None


def test_crawl_retry_policy_is_transient_only() -> None:
    assert _retryable_crawl_error(TimeoutError("timeout"))
    assert _retryable_crawl_error(ConnectionError("connection"))
    assert not _retryable_crawl_error(ValueError("invalid extraction"))
    transient = RetryableCrawlError("transient", http_status=503)
    assert transient.http_status == 503


def test_relative_canonical_is_resolved_and_network_checked(monkeypatch) -> None:
    html = '<link rel="canonical" href="../canonical/article?utm_source=test">'
    assert _canonical_candidate(html, "https://public.example/news/item") == (
        "https://public.example/canonical/article"
    )

    async def allowed(url: str):
        return UrlPolicyResult(url, True, "allowed")

    monkeypatch.setattr("ai_websearch.scrape.check_url_network", allowed)
    assert (
        asyncio.run(_canonical(html, "https://public.example/news/item"))
        == "https://public.example/canonical/article"
    )


def test_nonpublic_canonical_falls_back_to_final_url(monkeypatch) -> None:
    html = '<link rel="canonical" href="https://canonical.example/private">'

    async def denied(url: str):
        return UrlPolicyResult(url, False, "non-public")

    monkeypatch.setattr("ai_websearch.scrape.check_url_network", denied)
    assert (
        asyncio.run(_canonical(html, "https://public.example/article"))
        == "https://public.example/article"
    )
    assert (
        classify_access_outcome(
            "Welcome",
            '<form id="login-form" action="/session"><input type="password"></form>',
            "",
        )
        == "authentication"
    )


def test_long_consent_page_is_not_accepted_as_article_content() -> None:
    consent = " ".join(
        [
            "Manage your privacy. Accept all cookies. Consent preferences include "
            "advertising partners, precise geolocation data, and legitimate interests."
        ]
        * 100
    )
    assert classify_access_outcome("Privacy choices", None, consent) == "cookie_consent"


def test_domain_rate_limiter_spaces_starts_for_same_domain() -> None:
    limiter = DomainRateLimiter(concurrency=2, min_interval_seconds=0.01)
    starts: list[float] = []

    async def work() -> None:
        async with limiter.acquire("https://example.test/article"):
            starts.append(time.monotonic())

    async def run_both() -> None:
        await asyncio.gather(work(), work())

    asyncio.run(run_both())
    assert starts[1] - starts[0] >= 0.008


def _store(path: Path, topic: str, text: str, fetched_at: str = "2026-08-01T00:00:00+00:00"):
    original = settings.database_path
    settings.database_path = str(path)
    try:
        return store.store_document(
            "https://example.test/article",
            "https://example.test/article",
            "Example",
            text,
            fetched_at,
            None,
            topic,
            [text],
            np.array([[1.0, 0.0]], dtype=np.float32),
        )
    finally:
        settings.database_path = original


def test_cache_hit_associates_existing_content_with_new_topic(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    _store(path, "topic-a", "useful evidence")
    original = settings.database_path
    settings.database_path = str(path)
    try:
        hit = store.find_fresh_source(
            "https://example.test/article", "topic-b", ttl_hours=24 * 3650
        )
        assert hit is not None and hit.cache_status == "fresh_hit"
        assert len(store.fetch_all_chunks("topic-a")) == 1
        assert len(store.fetch_all_chunks("topic-b")) == 1
    finally:
        settings.database_path = original


def test_failed_refresh_reuses_stale_good_content_for_new_topic(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "stale.sqlite3"
    _store(path, "topic-a", "stale but useful evidence", "2020-01-01T00:00:00+00:00")
    original = settings.database_path
    settings.database_path = str(path)

    async def wall(*_args, **_kwargs):
        return ScrapedPage(
            url="https://example.test/article",
            canonical_url="https://example.test/article",
            fetched_at="2026-08-02T00:00:00Z",
            success=False,
            outcome="captcha",
            http_status=403,
            error="crawl access outcome: captcha",
        )

    async def should_not_embed(*_args, **_kwargs):
        raise AssertionError("stale fallback reached embeddings")

    monkeypatch.setattr(orchestrator, "scrape_url", wall)
    monkeypatch.setattr(orchestrator.embedder, "embed_texts", should_not_embed)
    try:
        result = asyncio.run(orchestrator.ingest_url("https://example.test/article", "topic-b"))
        assert result.ok
        assert result.cache_status == "stale_fallback"
        assert result.refresh_outcome == "captcha"
        assert result.http_status == 403
        assert len(store.fetch_all_chunks("topic-a")) == 1
        assert len(store.fetch_all_chunks("topic-b")) == 1
    finally:
        settings.database_path = original


def test_changed_content_keeps_history_but_only_latest_is_retrievable(tmp_path: Path) -> None:
    path = tmp_path / "versions.sqlite3"
    first = _store(path, "topic", "old evidence", "2026-07-01T00:00:00+00:00")
    second = _store(path, "topic", "new evidence", "2026-08-01T00:00:00+00:00")
    original = settings.database_path
    settings.database_path = str(path)
    try:
        with store.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2
            assert (
                connection.execute("SELECT COUNT(*) FROM sources WHERE active = 1").fetchone()[0]
                == 1
            )
        rows = store.fetch_all_chunks("topic")
        assert len(rows) == 1 and rows[0]["text"] == "new evidence"
        assert first.source_id != second.source_id
    finally:
        settings.database_path = original


def test_access_wall_is_not_embedded_or_stored(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "find_fresh_source", lambda *_args, **_kwargs: None)

    async def wall(*_args, **_kwargs):
        return ScrapedPage(
            url="https://example.test",
            canonical_url="https://example.test",
            fetched_at="2026-08-01T00:00:00Z",
            success=False,
            outcome="captcha",
            http_status=403,
            error="crawl access outcome: captcha",
        )

    async def should_not_embed(*_args, **_kwargs):
        raise AssertionError("wall content reached embeddings")

    monkeypatch.setattr(orchestrator, "scrape_url", wall)
    monkeypatch.setattr(orchestrator.embedder, "embed_texts", should_not_embed)
    result = asyncio.run(orchestrator.ingest_url("https://example.test", "topic"))
    assert not result.ok
    assert result.outcome == "captcha"
    assert result.http_status == 403
    assert "manual_action_available" not in type(result).model_fields


def test_ingestion_embeds_and_stores_clean_chunks(monkeypatch) -> None:
    observed: dict[str, list[str]] = {}
    monkeypatch.setattr(orchestrator, "find_fresh_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "find_stale_source", lambda *_args, **_kwargs: None)

    async def page(*_args, **_kwargs):
        return ScrapedPage(
            url="https://example.test",
            canonical_url="https://example.test",
            title="Example",
            markdown="Clean factual evidence for retrieval.",
            fetched_at="2026-08-02T00:00:00Z",
            content_hash="hash",
            http_status=200,
            success=True,
        )

    async def embed(chunks):
        observed["embedded"] = list(chunks)
        return np.asarray([[1.0, 0.0]], dtype=np.float32)

    def store_document(*_args, **_kwargs):
        observed["stored"] = list(_args[-2])
        return IngestResult(ok=True, url="https://example.test")

    monkeypatch.setattr(orchestrator, "scrape_url", page)
    monkeypatch.setattr(orchestrator, "reuse_stored_content", lambda *_args: None)
    monkeypatch.setattr(orchestrator, "chunk_text", lambda _text: ["Clean factual evidence."])
    monkeypatch.setattr(orchestrator.embedder, "embed_texts", embed)
    monkeypatch.setattr(orchestrator, "store_document", store_document)
    result = asyncio.run(orchestrator.ingest_url("https://example.test", "topic"))
    assert result.ok
    assert result.http_status == 200
    assert observed == {
        "embedded": ["Clean factual evidence."],
        "stored": ["Clean factual evidence."],
    }


def test_nonempty_legacy_embedding_representation_requires_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "legacy-input.sqlite3"
    _store(path, "topic", "legacy evidence")
    original = settings.database_path
    settings.database_path = str(path)
    try:
        with store.connect() as connection:
            connection.execute("DELETE FROM rag_metadata WHERE key = 'embedding_input_version'")
            connection.commit()
        try:
            store.initialize_database()
        except Exception as exc:
            assert getattr(exc, "code", None) == "embedding_model_mismatch"
        else:
            raise AssertionError("legacy embedding representation was accepted")
    finally:
        settings.database_path = original


def test_previous_chunk_representation_requires_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "previous-chunks.sqlite3"
    _store(path, "topic", "previous chunk evidence")
    original = settings.database_path
    settings.database_path = str(path)
    try:
        with store.connect() as connection:
            connection.execute(
                "UPDATE rag_metadata SET value = 'clean_chunks_v2' "
                "WHERE key = 'embedding_input_version'"
            )
            connection.commit()
        try:
            store.initialize_database()
        except Exception as exc:
            assert getattr(exc, "code", None) == "embedding_model_mismatch"
            assert getattr(exc, "details", {})["configured_input_version"] == "clean_sections_v3"
        else:
            raise AssertionError("the previous chunk representation was accepted")
    finally:
        settings.database_path = original


def test_publication_date_provenance_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "publication.sqlite3"
    original = settings.database_path
    settings.database_path = str(path)
    try:
        result = store.store_document(
            "https://example.test/dated",
            "https://example.test/dated",
            "Dated evidence",
            "Useful dated public evidence.",
            "2026-08-02T00:00:00Z",
            "2026-08-01T10:00:00+00:00",
            "topic",
            ["Useful dated public evidence."],
            np.asarray([[1.0, 0.0]], dtype=np.float32),
            published_at_source="json_ld",
        )
        assert result.published_at_source == "json_ld"
        row = store.fetch_all_chunks("topic")[0]
        assert row["published_at"] == "2026-08-01T10:00:00+00:00"
        assert row["published_at_source"] == "json_ld"
    finally:
        settings.database_path = original


def test_cache_audit_quarantines_wall_content_without_deleting_it(tmp_path: Path) -> None:
    path = tmp_path / "quality.sqlite3"
    original = settings.database_path
    settings.database_path = str(path)
    try:
        with store.connect() as connection:
            connection.execute(
                """INSERT INTO sources(
                       url, canonical_url, title, domain, topic, fetched_at,
                       content_hash, markdown, active
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    "https://wall.test",
                    "https://wall.test",
                    "Privacy choices",
                    "wall.test",
                    "topic",
                    "2026-08-01T00:00:00Z",
                    "hash",
                    " ".join(
                        [
                            "Manage your privacy. Accept all cookies. Consent preferences "
                            "include advertising partners and legitimate interests."
                        ]
                        * 100
                    ),
                ),
            )
            connection.commit()

        dry_run = store.audit_source_quality(apply=False)
        assert dry_run["quarantined"] == 1
        with store.connect() as connection:
            assert (
                connection.execute("SELECT quality_status FROM sources").fetchone()[0] == "unknown"
            )

        applied = store.audit_source_quality(apply=True)
        assert applied["quarantined"] == 1
        with store.connect() as connection:
            row = connection.execute("SELECT quality_status, active FROM sources").fetchone()
            assert tuple(row) == ("quarantined", 1)
            assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert store.fetch_all_chunks("topic") == []
    finally:
        settings.database_path = original
