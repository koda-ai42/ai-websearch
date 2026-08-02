from __future__ import annotations

from pathlib import Path

CASES = (
    {
        "id": "fast-success",
        "deadline_seconds": 5.0,
        "operations": [(0.4, "success")],
        "expected": "success",
    },
    {
        "id": "transient-retry-overrun",
        "deadline_seconds": 1.5,
        "operations": [(1.0, "transient"), (1.0, "success")],
        "expected": "deadline_exceeded",
    },
    {
        "id": "slow-first-attempt",
        "deadline_seconds": 0.5,
        "operations": [(2.0, "success")],
        "expected": "deadline_exceeded",
    },
    {
        "id": "terminal-failure",
        "deadline_seconds": 5.0,
        "operations": [(0.2, "terminal")],
        "expected": "terminal",
    },
)


def _run(case: dict, bounded: bool) -> dict:
    elapsed = 0.0
    observed = "terminal"
    for index, (duration, outcome) in enumerate(case["operations"]):
        remaining = case["deadline_seconds"] - elapsed
        if bounded and duration > max(0.0, remaining):
            elapsed = case["deadline_seconds"]
            observed = "deadline_exceeded"
            break
        elapsed += duration
        observed = outcome
        if outcome != "transient":
            break
        if index + 1 < len(case["operations"]):
            backoff = 0.5 * (index + 1)
            if bounded and backoff >= case["deadline_seconds"] - elapsed:
                elapsed = case["deadline_seconds"]
                observed = "deadline_exceeded"
                break
            elapsed += backoff
    return {
        "id": case["id"],
        "expected": case["expected"],
        "observed": observed,
        "elapsed_seconds": elapsed,
        "within_deadline": elapsed <= case["deadline_seconds"],
        "correct": observed == case["expected"],
    }


def run_request_deadline_benchmark(_path: Path | None = None) -> dict:
    policies = {}
    for name, bounded in (("operation_timeouts_only", False), ("remaining_request_deadline", True)):
        rows = [_run(case, bounded) for case in CASES]
        policies[name] = {
            "accuracy": {
                "outcome_accuracy": sum(row["correct"] for row in rows) / len(rows),
            },
            "reliability": {
                "deadline_compliance": sum(row["within_deadline"] for row in rows) / len(rows),
                "distinct_deadline_outcome": bounded,
            },
            "cases": rows,
        }
    return {
        "schema_version": "1.0",
        "run_mode": "offline_request_deadline_policy",
        "policies": policies,
        "latency": {"measured": False, "cases_evaluated": len(CASES)},
        "limitations": [
            "Durations are deterministic fixture arithmetic, not observed wall-clock timings.",
            "Cancellation cleanup for HTTP and Chromium remains a live integration check.",
        ],
    }
