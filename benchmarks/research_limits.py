from __future__ import annotations

from typing import Any

from ai_websearch import research_controller, retrieval_policy

TARGET_DEFAULTS = {
    "rapid": {"max_page_attempts": 2, "max_sources": 2, "max_chunks": 8},
    "auto": {"max_page_attempts": 5, "max_sources": 5, "max_chunks": 15},
    "deep": {"max_page_attempts": 10, "max_sources": 8, "max_chunks": 24},
}


def _legacy_snapshot() -> dict[str, dict[str, int]]:
    # Frozen from the pre-change production resolver and recorded in the before artifact.
    rapid = {"max_page_attempts": 2, "max_sources": 3, "max_chunks": 8}
    deep = {"max_page_attempts": 10, "max_sources": 8, "max_chunks": 24}
    return {
        "rapid": rapid,
        "auto": {
            "max_page_attempts": rapid["max_page_attempts"] + deep["max_page_attempts"],
            "max_sources": deep["max_sources"],
            "max_chunks": deep["max_chunks"],
        },
        "deep": deep,
    }


def _production_snapshot() -> tuple[str, dict[str, dict[str, int]]]:
    resolver = getattr(retrieval_policy, "resolve_research_mode_limits", None)
    if resolver is None:
        return "legacy_depth_adapter", _legacy_snapshot()
    return (
        "mode_specific_request_limits",
        {mode: resolver(100_000, mode).effective_metadata() for mode in ("rapid", "auto", "deep")},
    )


def _auto_progression_snapshot(implementation: str) -> dict[str, Any]:
    if implementation == "legacy_depth_adapter":
        observed = {
            "simple_initial_pass": "rapid",
            "complex_initial_pass": "deep",
            "escalation_page_ceiling": 10,
            "deep_evidence_checkpoints": [10],
        }
    else:
        resolved = retrieval_policy.resolve_research_mode_limits(100_000, "auto")
        observed = {
            "simple_initial_pass": research_controller.initial_pass("auto"),
            "complex_initial_pass": research_controller.initial_pass("auto"),
            "escalation_page_ceiling": retrieval_policy.calculate_research_pass_limits(
                resolved,
                "deep",
                resolved.max_page_attempts,
            ).max_page_attempts,
            "deep_evidence_checkpoints": list(retrieval_policy.evidence_checkpoints(10)),
        }
    target = {
        "simple_initial_pass": "rapid",
        "complex_initial_pass": "rapid",
        "escalation_page_ceiling": 3,
        "deep_evidence_checkpoints": [2, 5, 10],
    }
    checks = {key: observed[key] == value for key, value in target.items()}
    return {
        "target": target,
        "observed": observed,
        "matches": checks,
        "contract_conformance": sum(checks.values()) / len(checks),
        "contract_violations": len(checks) - sum(checks.values()),
    }


def run_research_limits_benchmark(_path=None) -> dict[str, Any]:
    implementation, observed = _production_snapshot()
    progression = _auto_progression_snapshot(implementation)
    comparisons = 0
    matches = 0
    rows: list[dict[str, Any]] = []
    bound_violations = 0
    for mode, target in TARGET_DEFAULTS.items():
        actual = observed[mode]
        field_matches = {field: actual[field] == expected for field, expected in target.items()}
        comparisons += len(field_matches)
        matches += sum(field_matches.values())
        if actual["max_page_attempts"] > target["max_page_attempts"]:
            bound_violations += 1
        rows.append({"mode": mode, "target": target, "observed": actual, "matches": field_matches})

    total_page_attempts = sum(item["max_page_attempts"] for item in observed.values())
    target_total_page_attempts = sum(item["max_page_attempts"] for item in TARGET_DEFAULTS.values())
    return {
        "schema_version": "1.0",
        "run_mode": "offline_production_policy",
        "implementation": implementation,
        "accuracy": {
            "answer_quality_measured": False,
            "mode_limit_policy_conformance": matches / comparisons,
            "matching_limit_fields": matches,
            "limit_fields_evaluated": comparisons,
        },
        "reliability": {
            "request_wide_page_bound_violations": bound_violations,
            "progression_contract_violations": progression["contract_violations"],
            "modes_evaluated": len(TARGET_DEFAULTS),
            "network_access": False,
            "model_inference": False,
        },
        "latency": {
            "measured": False,
            "synthetic_maximum_page_attempts_across_modes": total_page_attempts,
            "target_maximum_page_attempts_across_modes": target_total_page_attempts,
        },
        "modes": rows,
        "progression": progression,
        "limitations": [
            "This benchmark validates configured ceilings, not answer accuracy.",
            "Page-attempt totals are deterministic policy counts, not observed wall-clock latency.",
            "SearXNG, Chromium, embeddings, reranking, llama.cpp, and WebUI are not executed.",
        ],
    }
