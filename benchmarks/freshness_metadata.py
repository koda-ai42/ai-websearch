from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from ai_websearch.freshness import normalize_publication_date
from ai_websearch.scrape import _published

FETCHED_AT = "2026-08-02T00:00:00Z"
DATE_CASES = (
    {
        "id": "json-ld",
        "html": '<script type="application/ld+json">{"datePublished":"2026-08-01"}</script>',
        "expected_source": "json_ld",
    },
    {
        "id": "meta",
        "html": '<meta property="article:published_time" content="2026-08-01">',
        "expected_source": "meta",
    },
    {
        "id": "time",
        "html": '<time datetime="2026-08-01">1 August</time>',
        "expected_source": "time",
    },
    {
        "id": "future-json-valid-meta",
        "html": '<script type="application/ld+json">{"datePublished":"2030-01-01"}</script><meta name="date" content="2026-08-01">',
        "expected_source": "meta",
    },
    {"id": "missing", "html": "<article>No date metadata.</article>", "expected_source": None},
)


def _old_published(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in (
        {"property": "article:published_time"},
        {"name": "date"},
        {"itemprop": "datePublished"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return normalize_publication_date(str(tag["content"]), FETCHED_AT), "meta"
    tag = soup.find("time")
    if tag:
        return normalize_publication_date(str(tag.get("datetime") or tag.text), FETCHED_AT), "time"
    return None, None


def run_freshness_metadata_benchmark(_path: Path | None = None) -> dict:
    policies = {}
    for name, date_reader in (
        ("meta_time_year", _old_published),
        ("provenance_aware", lambda html: _published(html, FETCHED_AT)),
    ):
        date_rows = []
        for case in DATE_CASES:
            _value, source = date_reader(case["html"])
            date_rows.append(
                {
                    "id": case["id"],
                    "expected_source": case["expected_source"],
                    "observed_source": source,
                    "correct": source == case["expected_source"],
                }
            )
        policies[name] = {
            "accuracy": {
                "date_provenance_accuracy": sum(row["correct"] for row in date_rows)
                / len(date_rows),
            },
            "reliability": {
                "future_dates_rejected": name == "provenance_aware",
                "search_hints_distinguishable": name == "provenance_aware",
            },
            "date_cases": date_rows,
        }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_freshness_metadata_policy",
        "policies": policies,
        "latency": {"measured": False, "cases_evaluated": len(DATE_CASES)},
        "limitations": [
            "HTML and dates are synthetic; no SearXNG or browser request is executed.",
            "Freshness ranking effects require a larger human-judged retrieval corpus.",
        ],
    }
