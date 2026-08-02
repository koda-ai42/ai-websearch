from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metrics import mean
from .trace import STAGES, StageTracer

DEFAULT_STAGE4_CORPUS = Path(__file__).with_name("fixtures") / "stage4_v1" / "cache_corpus.json"
SAFE_OUTCOME = "success"
CACHE_STAGES = (*STAGES, "database_read")


@dataclass(frozen=True)
class CachePolicy:
    name: str
    consult_before_refresh: bool
    reject_non_success: bool
    unchanged_before_processing: bool
    version_semantics: str


CACHE_POLICIES = {
    policy.name: policy
    for policy in (
        CachePolicy("current_append_model", False, False, False, "append_all_active"),
        CachePolicy("replace_active", True, True, True, "replace"),
        CachePolicy("retain_history_single_active", True, True, True, "retain_single_active"),
    )
}


def load_stage4_corpus(path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    selected = (path or DEFAULT_STAGE4_CORPUS).resolve()
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if payload.get("version") != "2026-07-14.stage4.v1":
        raise ValueError("unsupported Stage 4 corpus version")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Stage 4 corpus requires scenarios")
    return selected, payload


def _active(versions: list[dict]) -> list[dict]:
    return [version for version in versions if version["active"]]


def _store_version(versions: list[dict], event: dict[str, Any], policy: CachePolicy) -> None:
    version = {
        "content_hash": event["content_hash"],
        "canonical_url": event["canonical_url"],
        "fetched_at_hour": event["at_hour"],
        "outcome": event["outcome"],
        "active": True,
        "provenance": event["provenance"],
    }
    if policy.version_semantics == "replace":
        versions[:] = [version]
    elif policy.version_semantics == "retain_single_active":
        for existing in versions:
            existing["active"] = False
        versions.append(version)
    else:
        versions.append(version)


def _run_scenario(
    scenario: dict[str, Any], policy: CachePolicy
) -> tuple[dict, Counter, StageTracer]:
    versions: list[dict] = []
    operations: Counter = Counter()
    tracer = StageTracer(stages=CACHE_STAGES)
    cache_hits = 0
    wall_cached = 0
    unchanged_skips = 0
    failed_refreshes = 0
    for event in scenario["events"]:
        before = len(tracer.events)
        active = _active(versions)
        newest = max(active, key=lambda item: item["fetched_at_hour"], default=None)
        fresh = (
            newest is not None
            and event["at_hour"] - newest["fetched_at_hour"] <= scenario["ttl_hours"]
        )
        if policy.consult_before_refresh:
            operations["cache_read_before_refresh"] += 1
            tracer.record("database_read", 0.02)
            if fresh:
                cache_hits += 1
                operations["cache_hit"] += 1
                tracer.record("total", sum(item.duration_ms for item in tracer.events[before:]))
                continue

        operations["refresh"] += 1
        crawl_ok = bool(event["crawl_success"])
        tracer.record("crawl_extraction", float(event.get("crawl_duration_ms", 5.0)), crawl_ok)
        if not crawl_ok:
            failed_refreshes += 1
            operations["refresh_failure"] += 1
            tracer.record("total", sum(item.duration_ms for item in tracer.events[before:]))
            continue

        outcome = event["outcome"]
        if policy.reject_non_success and outcome != SAFE_OUTCOME:
            operations["rejected_non_success"] += 1
            tracer.record("total", sum(item.duration_ms for item in tracer.events[before:]))
            continue

        operations["content_identity_read"] += 1
        tracer.record("database_read", 0.02)
        matching = next(
            (
                version
                for version in versions
                if version["canonical_url"] == event["canonical_url"]
                and version["content_hash"] == event["content_hash"]
            ),
            None,
        )
        if matching is not None and policy.unchanged_before_processing:
            if policy.version_semantics == "retain_single_active" and not matching["active"]:
                for version in versions:
                    version["active"] = False
                matching["active"] = True
                operations["historical_reactivation"] += 1
            matching["fetched_at_hour"] = event["at_hour"]
            unchanged_skips += 1
            operations["unchanged_preprocess_skip"] += 1
            tracer.record("total", sum(item.duration_ms for item in tracer.events[before:]))
            continue

        operations["chunk"] += 1
        operations["embed"] += 1
        tracer.record("chunking", 0.06)
        tracer.record("embedding_encode", 0.4)
        if matching is not None:
            matching["fetched_at_hour"] = event["at_hour"]
            operations["duplicate_after_processing"] += 1
            tracer.record("total", sum(item.duration_ms for item in tracer.events[before:]))
            continue

        operations["cache_write"] += 1
        tracer.record("database_write", 0.2)
        _store_version(versions, event, policy)
        wall_cached += outcome != SAFE_OUTCOME
        tracer.record("total", sum(item.duration_ms for item in tracer.events[before:]))

    active = _active(versions)
    expected = scenario["expected"]
    active_hashes = [version["content_hash"] for version in active]
    expected_hash = expected.get("active_content_hash")
    good_preserved = (
        (expected_hash in active_hashes if expected_hash else not active_hashes)
        if expected.get("tests_good_preservation")
        else None
    )
    wall_rejected = wall_cached == 0 if expected.get("tests_wall_rejection") else None
    single_active = (
        len(active) == expected["active_versions"]
        if expected.get("tests_version_semantics")
        else None
    )
    unchanged_avoided = (
        operations["embed"]
        == expected.get("embedding_operations_by_policy", {}).get(
            policy.name, expected["safe_embedding_operations"]
        )
        if expected.get("tests_unchanged_detection")
        else None
    )
    cache_consulted = (
        cache_hits == expected["safe_cache_hits"] if expected.get("tests_cache_hit") else None
    )
    applicable = [
        value
        for value in (
            good_preserved,
            wall_rejected,
            single_active,
            unchanged_avoided,
            cache_consulted,
        )
        if value is not None
    ]
    scenario_correct = all(applicable)
    return (
        {
            "id": scenario["id"],
            "active_content_hashes": active_hashes,
            "stored_versions": len(versions),
            "active_versions": len(active),
            "cache_hits": cache_hits,
            "wall_results_cached": wall_cached,
            "failed_refreshes": failed_refreshes,
            "unchanged_preprocess_skips": unchanged_skips,
            "embedding_operations": operations["embed"],
            "good_content_preserved": good_preserved,
            "wall_rejected": wall_rejected,
            "single_active_version_correct": single_active,
            "unchanged_work_avoided": unchanged_avoided,
            "cache_consulted_before_refresh": cache_consulted,
            "scenario_correct": scenario_correct,
            "provenance_complete": all(bool(version["provenance"]) for version in versions),
        },
        operations,
        tracer,
    )


def _run_policy(scenarios: list[dict[str, Any]], policy: CachePolicy) -> dict:
    results: list[dict] = []
    operations: Counter = Counter()
    combined_tracer = StageTracer(stages=CACHE_STAGES)
    for scenario in scenarios:
        result, scenario_operations, tracer = _run_scenario(scenario, policy)
        results.append(result)
        operations.update(scenario_operations)
        combined_tracer.events.extend(tracer.events)
    metric_fields = {
        "good_content_preservation_rate": "good_content_preserved",
        "wall_rejection_rate": "wall_rejected",
        "single_active_version_rate": "single_active_version_correct",
        "unchanged_work_avoidance_rate": "unchanged_work_avoided",
        "cache_before_refresh_rate": "cache_consulted_before_refresh",
    }
    accuracy: dict[str, float | int] = {
        "scenario_correctness": mean([float(result["scenario_correct"]) for result in results])
    }
    for metric, field in metric_fields.items():
        values = [float(result[field]) for result in results if result[field] is not None]
        accuracy[metric] = mean(values)
        accuracy[metric.removesuffix("_rate") + "_applicable_cases"] = len(values)
    return {
        "accuracy": {
            **accuracy,
        },
        "reliability": {
            "operation_counts": dict(sorted(operations.items())),
            "wall_results_cached": sum(result["wall_results_cached"] for result in results),
            "failed_refreshes": sum(result["failed_refreshes"] for result in results),
            "provenance_complete": all(result["provenance_complete"] for result in results),
            "version_semantics": policy.version_semantics,
        },
        "latency": combined_tracer.summary(),
        "scenarios": results,
    }


def run_stage4_benchmark(corpus_path: Path | None = None) -> dict:
    path, corpus = load_stage4_corpus(corpus_path)
    try:
        display_path = str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(path)
    return {
        "schema_version": "1.0",
        "run_mode": "offline_stage4_cache_policy_replay",
        "corpus": {"version": corpus["version"], "path": display_path},
        "evaluation_protocol": {
            "scope": "In-memory URL/canonical cache policy and version-semantics modeling only.",
            "latency": "Deterministic fixture durations and operation counts, not live cache measurements.",
            "peak_rss_bytes": "Not measured during offline replay; reported as null.",
            "database_access": "No SQLite database is opened by Stage 4 replay.",
        },
        "policies": {
            name: _run_policy(corpus["scenarios"], policy)
            for name, policy in CACHE_POLICIES.items()
        },
        "live_integrations_executed": [],
    }
