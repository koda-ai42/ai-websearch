from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from ai_websearch import clean
from ai_websearch.chunking import chunk_text
from ai_websearch.integration_contract import ANSWER_AGENT_INSTRUCTIONS

DEFAULT_CORPUS = Path(__file__).with_name("fixtures") / "temporal_schedule_v1" / "corpus.json"
_CONSENT_MARKERS = (
    "consent to cookies",
    "selecting i accept",
    "reject all",
    "precise geolocation",
)


def _boilerplate_cleaner() -> Callable[[str], str]:
    candidate = getattr(clean, "strip_page_boilerplate", None)
    return candidate if callable(candidate) else clean.clean_markdown


def _contract_behavior_controls(validator: Any) -> dict[str, bool]:
    controls = {
        "citation_and_fetch_required": False,
        "original_query_enforced": False,
    }
    if not callable(validator):
        return controls
    fetched_at = "2026-08-02T16:38:50+00:00"
    citation = "[Release notes](https://example.test/releases/latest)"
    sources = [{"citation": citation, "fetched_at": fetched_at}]
    query = "What changed in the latest stable release?"
    common = {
        "original_query": query,
        "research_queries": [query],
        "tool_names": ["research"],
        "sources": sources,
        "answerable": True,
    }
    missing_reference = validator(answer="The release improves retrieval.", **common)
    changed_query = validator(
        original_query=query,
        research_queries=["latest release notes"],
        tool_names=["research"],
        answer=f"The release improves retrieval. {citation} fetched {fetched_at}.",
        sources=sources,
        answerable=True,
    )
    controls["citation_and_fetch_required"] = (
        "missing_required_citation_or_fetched_date" in missing_reference["violations"]
    )
    controls["original_query_enforced"] = (
        "original_query_not_preserved" in changed_query["violations"]
    )
    return controls


def run_temporal_schedule_benchmark(path: Path | None = None) -> dict[str, Any]:
    selected = (path or DEFAULT_CORPUS).resolve()
    corpus = json.loads(selected.read_text(encoding="utf-8"))

    chunking_case = corpus["chunking_case"]
    chunks = chunk_text(
        str(chunking_case["markdown"]),
        chunk_size=int(chunking_case["chunk_size"]),
        overlap=int(chunking_case["overlap"]),
        min_chunk_chars=int(chunking_case["min_chunk_chars"]),
    )
    section_heading = str(chunking_case["section_heading"])
    tail_marker = str(chunking_case["tail_marker"])
    orphaned_section_chunks = [
        chunk for chunk in chunks if tail_marker in chunk and section_heading not in chunk
    ]
    broken_starts = [
        chunk.splitlines()[0]
        for chunk in chunks[1:]
        if re.match(r"^(?:[a-z]|\d{1,2}\))", chunk.strip())
    ]

    consent_markdown = str(corpus["consent_case"]["markdown"])
    cleaned = _boilerplate_cleaner()(consent_markdown)
    lowered_cleaned = cleaned.casefold()
    remaining_markers = [marker for marker in _CONSENT_MARKERS if marker in lowered_cleaned]

    transaction_validator = getattr(
        __import__(
            "ai_websearch.integration_contract",
            fromlist=["validate_answer_transaction"],
        ),
        "validate_answer_transaction",
        None,
    )
    contract_controls = {
        "original_query_required": "original user question unchanged"
        in ANSWER_AGENT_INSTRUCTIONS.casefold(),
        "scope_instruction_present": "do not add related" in ANSWER_AGENT_INSTRUCTIONS.casefold(),
        "transaction_validator_available": callable(transaction_validator),
        **_contract_behavior_controls(transaction_validator),
    }
    section_checks = [not orphaned_section_chunks, not broken_starts]
    return {
        "schema_version": "1.0",
        "corpus_version": corpus["version"],
        "run_mode": "offline_production_policy",
        "accuracy": {
            "section_boundary_accuracy": sum(section_checks) / len(section_checks),
            "orphaned_section_fragments": len(orphaned_section_chunks),
            "broken_chunk_starts": len(broken_starts),
        },
        "reliability": {
            "consent_markers_remaining": remaining_markers,
            "answer_contract_controls": contract_controls,
        },
        "latency": {
            "measured": False,
            "chunks_produced": len(chunks),
            "section_checks_evaluated": len(section_checks),
        },
        "chunking": {
            "chunks": chunks,
            "orphaned_section_fragments": orphaned_section_chunks,
            "broken_starts": broken_starts,
        },
        "limitations": [
            "The fixture is synthetic and derived from the observed UEFA page structure.",
            "No network, browser, embedding model, CrossEncoder, llama.cpp, or answer model runs.",
            "Latency fields are deterministic operation counts, not wall-clock measurements.",
        ],
    }
