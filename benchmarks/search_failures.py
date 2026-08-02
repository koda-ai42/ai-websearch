from __future__ import annotations

from pathlib import Path

CASES = (
    {"id": "partial", "successes": 1, "failures": 1, "results": 3, "expected": "partial_failure"},
    {"id": "all-failed", "successes": 0, "failures": 2, "results": 0, "expected": "total_failure"},
    {"id": "valid-empty", "successes": 2, "failures": 0, "results": 0, "expected": "empty_success"},
)


def _observed(case: dict, diagnostic: bool) -> str:
    if not diagnostic:
        return "success" if case["results"] else "empty_success"
    if case["failures"] and not case["successes"]:
        return "total_failure"
    if case["failures"]:
        return "partial_failure"
    return "empty_success" if not case["results"] else "success"


def run_search_failure_benchmark(_path: Path | None = None) -> dict:
    policies = {}
    for name, diagnostic in (("silent_failures", False), ("diagnostic_failures", True)):
        rows = [
            {
                "id": case["id"],
                "expected": case["expected"],
                "observed": _observed(case, diagnostic),
                "correct": _observed(case, diagnostic) == case["expected"],
            }
            for case in CASES
        ]
        policies[name] = {
            "accuracy": {
                "outcome_accuracy": sum(row["correct"] for row in rows) / len(rows),
            },
            "reliability": {
                "partial_failure_observable": diagnostic,
                "total_failure_raises": diagnostic,
                "valid_empty_distinct": diagnostic,
            },
            "cases": rows,
        }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_search_failure_policy",
        "policies": policies,
        "latency": {"measured": False, "cases_evaluated": len(CASES)},
        "limitations": [
            "Failure combinations are deterministic models; no SearXNG request is sent.",
            "Retry latency is excluded and must be measured against a synthetic local endpoint.",
        ],
    }
