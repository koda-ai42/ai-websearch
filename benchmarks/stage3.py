from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metrics import safe_ratio
from .trace import StageTracer

DEFAULT_STAGE3_CORPUS = Path(__file__).with_name("fixtures") / "stage3_v1" / "crawl_corpus.json"
OUTCOMES = {
    "success",
    "consent",
    "authentication",
    "captcha",
    "subscription",
    "access_denied",
    "empty_content",
    "extraction_failure",
}


@dataclass(frozen=True)
class ExtractionPolicy:
    name: str
    explicit_classification: bool
    markdown_order: tuple[str, ...]


EXTRACTION_POLICIES = {
    policy.name: policy
    for policy in (
        ExtractionPolicy("current_behavior_model", False, ("direct", "fit", "raw", "citations")),
        ExtractionPolicy(
            "explicit_current_precedence", True, ("direct", "fit", "raw", "citations")
        ),
        ExtractionPolicy("explicit_fit_first", True, ("fit", "raw", "citations", "direct")),
        ExtractionPolicy("explicit_raw_first", True, ("raw", "fit", "citations", "direct")),
        ExtractionPolicy("explicit_citations_first", True, ("citations", "fit", "raw", "direct")),
    )
}


def load_stage3_corpus(path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    selected = (path or DEFAULT_STAGE3_CORPUS).resolve()
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if payload.get("version") != "2026-07-14.stage3.v1":
        raise ValueError("unsupported Stage 3 corpus version")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Stage 3 corpus requires cases")
    outcomes = {case.get("expected_outcome") for case in cases}
    missing = sorted(OUTCOMES - outcomes)
    if missing:
        raise ValueError(f"Stage 3 corpus is missing outcomes: {', '.join(missing)}")
    return selected, payload


def select_markdown(case: dict[str, Any], order: tuple[str, ...]) -> tuple[str | None, str]:
    candidates = {
        "direct": case.get("direct_markdown"),
        "fit": case.get("markdown", {}).get("fit"),
        "raw": case.get("markdown", {}).get("raw"),
        "citations": case.get("markdown", {}).get("citations"),
    }
    for name in order:
        value = candidates.get(name)
        if isinstance(value, str) and value.strip():
            return name, value.strip()
    return None, ""


def _signal_text(case: dict[str, Any], markdown: str) -> str:
    values = [str(case.get("status", "")), str(case.get("html", "")), markdown]
    return " ".join(values).lower()


def classify_outcome(case: dict[str, Any], markdown: str, explicit: bool) -> str:
    if not case.get("crawl_success", False):
        return "extraction_failure"
    if not explicit:
        return "success" if markdown.strip() else "empty_content"
    signal = _signal_text(case, markdown)
    checks = (
        ("captcha", ("captcha", "verify you are human")),
        (
            "authentication",
            ("authentication required", "sign in to continue", "login required", " 401 "),
        ),
        ("subscription", ("subscription required", "subscribe to continue", "paywall")),
        ("access_denied", ("access denied", "forbidden", " 403 ")),
        ("consent", ("cookie consent", "accept cookies", "manage cookies")),
    )
    padded = f" {signal} "
    for outcome, markers in checks:
        if any(marker in padded for marker in markers):
            return outcome
    return "success" if markdown.strip() else "empty_content"


def _run_extraction_policy(cases: list[dict[str, Any]], policy: ExtractionPolicy) -> dict:
    tracer = StageTracer()
    results: list[dict] = []
    wall_total = 0
    wall_accepted = 0
    success_total = 0
    variant_correct = 0
    for case in cases:
        before = len(tracer.events)
        variant, markdown = select_markdown(case, policy.markdown_order)
        predicted = classify_outcome(case, markdown, policy.explicit_classification)
        expected = case["expected_outcome"]
        is_wall = expected in {
            "consent",
            "authentication",
            "captcha",
            "subscription",
            "access_denied",
        }
        if is_wall:
            wall_total += 1
            wall_accepted += predicted == "success"
        if expected == "success":
            success_total += 1
            variant_correct += variant == case.get("expected_markdown_variant")
        tracer.record(
            "crawl_extraction",
            float(case.get("classification_duration_ms", 0.1)),
            bool(case.get("crawl_success", False)),
        )
        tracer.record("total", sum(event.duration_ms for event in tracer.events[before:]))
        results.append(
            {
                "id": case["id"],
                "expected_outcome": expected,
                "predicted_outcome": predicted,
                "selected_markdown_variant": variant,
                "expected_markdown_variant": case.get("expected_markdown_variant"),
                "outcome_correct": predicted == expected,
                "wall_content_rejected": not is_wall or predicted != "success",
            }
        )
    correct = sum(case["outcome_correct"] for case in results)
    return {
        "accuracy": {
            "outcome_classification_accuracy": safe_ratio(correct, len(results)),
            "markdown_variant_accuracy": safe_ratio(variant_correct, success_total),
            "wall_rejection_rate": safe_ratio(wall_total - wall_accepted, wall_total),
        },
        "reliability": {
            "classified_outcomes": sorted({case["predicted_outcome"] for case in results}),
            "misclassified_cases": len(results) - correct,
            "fixture_crawl_failures": sum(not case.get("crawl_success", False) for case in cases),
            "wall_pages_accepted_as_success": wall_accepted,
            "empty_success_pages": sum(
                case["predicted_outcome"] == "empty_content"
                and case["expected_outcome"] == "empty_content"
                for case in results
            ),
        },
        "latency": tracer.summary(),
        "cases": results,
    }


def _run_lifecycle(cases: list[dict[str, Any]], mode: str) -> dict:
    tracer = StageTracer()
    startup = float(cases[0].get("browser_startup_ms", 20.0))
    teardown = float(cases[0].get("browser_teardown_ms", 3.0))
    for index, case in enumerate(cases):
        navigation = float(case.get("navigation_ms", 10.0))
        if mode == "fresh_per_url":
            duration = startup + navigation + teardown
        else:
            duration = navigation
            if index == 0:
                duration += startup
            if index == len(cases) - 1:
                duration += teardown
        tracer.record("crawl_extraction", duration)
        tracer.record("total", duration)
    instances = len(cases) if mode == "fresh_per_url" else 1
    return {
        "accuracy": {"expected_outcome_preservation": None},
        "reliability": {
            "browser_instances": instances,
            "profile_mode": "ephemeral",
            "scope": "per_url" if mode == "fresh_per_url" else "benchmark_batch",
            "persistent_profile_used": False,
            "personal_profile_used": False,
            "browser_actions": "read_only_fixture_replay",
        },
        "latency": tracer.summary(),
    }


def run_stage3_benchmark(corpus_path: Path | None = None) -> dict:
    path, corpus = load_stage3_corpus(corpus_path)
    try:
        display_path = str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(path)
    cases = corpus["cases"]
    return {
        "schema_version": "1.0",
        "run_mode": "offline_stage3_crawl_extraction_replay",
        "corpus": {"version": corpus["version"], "path": display_path},
        "evaluation_protocol": {
            "scope": "Crawl outcome classification, Markdown selection, wall rejection, and browser lifecycle modeling only.",
            "latency": "Deterministic fixture durations and operation counts, not live browser measurements.",
            "peak_rss_bytes": "Not measured during offline replay; reported as null.",
            "lifecycle_accuracy": "Not evaluated by timing-only lifecycle modeling; outcome preservation is null.",
        },
        "extraction_policies": {
            name: _run_extraction_policy(cases, policy)
            for name, policy in EXTRACTION_POLICIES.items()
        },
        "lifecycle_policies": {
            mode: _run_lifecycle(cases, mode) for mode in ("fresh_per_url", "scoped_ephemeral")
        },
        "live_integrations_executed": [],
    }
