from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_websearch.config import Settings
from ai_websearch.logging_utils import URL_BEARING_DEPENDENCY_LOGGERS, JsonFormatter, setup_logging
from ai_websearch.security import markdown_citation, safe_url_label


def test_logging_suppresses_url_bearing_dependencies_and_trace_paths() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    dependency_levels = {
        name: logging.getLogger(name).level for name in URL_BEARING_DEPENDENCY_LOGGERS
    }
    try:
        setup_logging()
        assert all(
            logging.getLogger(name).level >= logging.WARNING
            for name in URL_BEARING_DEPENDENCY_LOGGERS
        )
        try:
            raise RuntimeError("/private/model/path")
        except RuntimeError:
            record = logging.LogRecord(
                "ai_websearch.test",
                logging.ERROR,
                __file__,
                1,
                "safe failure",
                (),
                sys.exc_info(),
            )
        rendered = JsonFormatter().format(record)
        assert '"exception_type": "RuntimeError"' in rendered
        assert "/private/model/path" not in rendered
        assert __file__ not in rendered
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
        for name, level in dependency_levels.items():
            logging.getLogger(name).setLevel(level)


def test_crawler_progress_logging_is_disabled() -> None:
    source = (Path(__file__).parents[1] / "src/ai_websearch/scrape.py").read_text()
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CrawlerRunConfig"
    ]
    assert len(calls) == 1
    values = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    assert isinstance(values["verbose"], ast.Constant)
    assert values["verbose"].value is False


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "example.test"])
def test_mcp_binding_rejects_non_loopback_hosts(host: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, mcp_host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_mcp_binding_accepts_loopback_hosts(host: str) -> None:
    assert Settings(_env_file=None, mcp_host=host).mcp_host == host


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://search.example.test",
        "http://user:secret@127.0.0.1:8888",
        "http://127.0.0.1:8888?token=secret",
        "http://127.0.0.1:8888#fragment",
    ],
)
def test_searxng_endpoint_rejects_nonlocal_or_sensitive_urls(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, searxng_url=endpoint)


def test_searxng_endpoint_accepts_a_loopback_path_and_normalizes_slash() -> None:
    settings = Settings(_env_file=None, searxng_url="http://127.0.0.1:8888/searxng/")
    assert settings.searxng_url == "http://127.0.0.1:8888/searxng"


def test_mcp_toolset_requires_an_explicit_supported_value() -> None:
    assert Settings(_env_file=None).mcp_toolset == "answer"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, mcp_toolset="everything")


def test_database_busy_timeout_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_busy_timeout_seconds=-0.1)


def test_safe_url_label_exposes_no_path_query_or_credentials() -> None:
    label = safe_url_label("https://user:secret@example.test/private/account?token=top-secret")
    assert label.startswith("https://example.test#sha256:")
    for forbidden in ("user", "secret", "private", "account", "token"):
        assert forbidden not in label


def test_markdown_citation_is_single_line_and_encodes_destination_breakout() -> None:
    citation = markdown_citation(
        "Unsafe\n[title]",
        "https://example.test/a)b(<?q=one two",
    )
    assert "\n" not in citation
    assert citation.startswith("[Unsafe \\[title\\]](")
    assert "%29" in citation and "%28" in citation and "%3C" in citation
    assert " " not in citation.split("](", 1)[1]
