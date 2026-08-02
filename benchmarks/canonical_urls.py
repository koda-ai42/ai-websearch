from __future__ import annotations

from pathlib import Path

from ai_websearch.clean import normalize_url
from ai_websearch.scrape import _canonical_candidate
from ai_websearch.url_policy import check_url

CASES = (
    {
        "id": "relative",
        "fallback": "https://example.test/news/item",
        "href": "../canonical",
        "expected": "https://example.test/canonical",
    },
    {
        "id": "absolute",
        "fallback": "https://example.test/item",
        "href": "https://publisher.test/story",
        "expected": "https://publisher.test/story",
    },
    {
        "id": "loopback",
        "fallback": "https://example.test/item",
        "href": "http://127.0.0.1/private",
        "expected": "https://example.test/item",
    },
    {
        "id": "credential-query",
        "fallback": "https://example.test/item",
        "href": "https://publisher.test/story?token=secret",
        "expected": "https://example.test/item",
    },
)


def _old_candidate(case: dict) -> str:
    candidate = normalize_url(case["href"])
    return candidate if check_url(candidate).allowed else normalize_url(case["fallback"])


def run_canonical_url_benchmark(_path: Path | None = None) -> dict:
    policies = {}
    for name, resolver in (
        ("unresolved_href", _old_candidate),
        (
            "resolved_policy_checked",
            lambda case: _canonical_candidate(
                f'<link rel="canonical" href="{case["href"]}">',
                case["fallback"],
            ),
        ),
    ):
        rows = [
            {
                "id": case["id"],
                "expected": case["expected"],
                "observed": resolver(case),
                "correct": resolver(case) == case["expected"],
            }
            for case in CASES
        ]
        policies[name] = {
            "accuracy": {
                "canonical_resolution_accuracy": sum(row["correct"] for row in rows) / len(rows)
            },
            "reliability": {
                "relative_urls_resolved": name == "resolved_policy_checked",
                "network_policy_required_before_storage": name == "resolved_policy_checked",
            },
            "cases": rows,
        }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_canonical_url_policy",
        "policies": policies,
        "latency": {"measured": False, "cases_evaluated": len(CASES)},
        "limitations": [
            "The benchmark exercises syntax/policy candidates without DNS resolution.",
            "Production additionally applies asynchronous public-network resolution.",
        ],
    }
