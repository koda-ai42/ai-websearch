from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ai_websearch.access_outcomes import classify_access_outcome
from ai_websearch.scrape import _crawl_result_outcome, _retryable_crawl_error

CASES = (
    {
        "id": "robots",
        "status": 403,
        "success": False,
        "headers": {"X-Robots-Status": "Blocked by robots.txt"},
        "title": "",
        "text": "",
        "expected": "robots_denied",
    },
    {
        "id": "not-found",
        "status": 404,
        "success": False,
        "headers": {},
        "title": "Not found",
        "text": "No article exists here.",
        "expected": "http_error",
    },
    {
        "id": "empty-success",
        "status": 200,
        "success": True,
        "headers": {},
        "title": "",
        "text": "",
        "expected": "empty_content",
    },
    {
        "id": "captcha-403",
        "status": 403,
        "success": False,
        "headers": {},
        "title": "Verify",
        "text": "Verify that you are human.",
        "expected": "captcha",
    },
    {
        "id": "authentication-401",
        "status": 401,
        "success": False,
        "headers": {},
        "title": "",
        "text": "",
        "expected": "authentication",
    },
    {
        "id": "public-success",
        "status": 200,
        "success": True,
        "headers": {},
        "title": "Public report",
        "text": "Substantive public evidence with methods and conclusions.",
        "expected": "success",
    },
)


def run_crawl_response_benchmark(_path: Path | None = None) -> dict:
    policies = {}
    for name, response_aware in (("content_only", False), ("response_aware", True)):
        rows = []
        for case in CASES:
            result = SimpleNamespace(
                status_code=case["status"],
                success=case["success"],
                response_headers=case["headers"],
                error_message="",
            )
            observed = (
                _crawl_result_outcome(result, case["title"], None, case["text"])
                if response_aware
                else classify_access_outcome(case["title"], None, case["text"])
            )
            rows.append(
                {
                    "id": case["id"],
                    "expected": case["expected"],
                    "observed": observed,
                    "correct": observed == case["expected"],
                }
            )
        policies[name] = {
            "accuracy": {
                "outcome_accuracy": sum(row["correct"] for row in rows) / len(rows),
            },
            "reliability": {
                "robots_distinct": response_aware,
                "http_status_used": response_aware,
                "empty_content_distinct": response_aware,
            },
            "cases": rows,
        }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_crawl_response_policy",
        "policies": policies,
        "retry_policy": {
            "timeout_retryable": _retryable_crawl_error(TimeoutError()),
            "connection_retryable": _retryable_crawl_error(ConnectionError()),
            "deterministic_value_error_retryable": _retryable_crawl_error(ValueError()),
        },
        "latency": {"measured": False, "cases_evaluated": len(CASES)},
        "limitations": [
            "CrawlResult objects are synthetic and no browser or robots request is executed.",
            "Retry delay and request deadlines are not timed.",
        ],
    }
