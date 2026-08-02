from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from .corpus import Corpus, load_corpus
from .metrics import (
    duplicate_rate,
    mean,
    ndcg,
    precision_recall,
    reciprocal_rank,
    safe_ratio,
    unique_domains,
)
from .trace import StageTracer

PIPELINES = ("phase1", "current")
SUCCESS_OUTCOME = "success"
DEFAULT_TIMINGS = {
    "query_planning": 0.05,
    "search_request": 4.0,
    "search_merge_dedup": 0.08,
    "crawl_extraction": 12.0,
    "cleaning": 0.04,
    "chunking": 0.06,
    "embedding_load": 3.0,
    "embedding_encode": 0.4,
    "database_write": 0.2,
    "fts": 0.3,
    "vector_scan": 0.5,
    "normalization_fusion": 0.05,
    "diversity_selection": 0.04,
    "rendering": 0.08,
    "llama_props": 1.0,
    "llama_tokenize": 0.7,
}


def _queries(query: str, pipeline: str) -> list[str]:
    if pipeline == "phase1":
        return [query.strip()]
    return [
        query.strip(),
        f"{query.strip()} official source",
        f"{query.strip()} technical documentation",
    ]


def _search(case: dict[str, Any], pipeline: str, tracer: StageTracer) -> tuple[list[dict], bool]:
    tracer.record("query_planning", DEFAULT_TIMINGS["query_planning"])
    output: list[dict] = []
    failed = False
    per_query_limit = 8 if pipeline == "phase1" else 10
    for query in _queries(case["query"], pipeline):
        response = case["search"].get(query)
        ok = isinstance(response, list)
        tracer.record("search_request", case.get("timings_ms", {}).get("search_request", 4.0), ok)
        if not ok:
            failed = True
            continue
        output.extend(deepcopy(response[:per_query_limit]))
    deduped = {item["url"]: item for item in output}
    limit = 8 if pipeline == "phase1" else 10
    ranked = sorted(
        deduped.values(),
        key=lambda item: (float(item.get("source_score", 0.5)), float(item.get("score", 0.0))),
        reverse=True,
    )[:limit]
    tracer.record("search_merge_dedup", DEFAULT_TIMINGS["search_merge_dedup"])
    return ranked, failed


def _crawl(
    case: dict[str, Any],
    ranked: list[dict],
    pipeline: str,
    tracer: StageTracer,
    embedding_loaded: bool,
) -> tuple[list[dict], Counter, bool]:
    page_limit = 4 if pipeline == "phase1" else 5
    pages: list[dict] = []
    outcomes: Counter = Counter()
    for result in ranked[:page_limit]:
        page = deepcopy(
            case["crawls"].get(result["url"], {"outcome": "extraction_failure", "chunks": []})
        )
        page["url"] = result["url"]
        outcome = page.get("outcome", "extraction_failure")
        outcomes[outcome] += 1
        ok = outcome == SUCCESS_OUTCOME
        tracer.record(
            "crawl_extraction", page.get("duration_ms", DEFAULT_TIMINGS["crawl_extraction"]), ok
        )
        if not ok:
            continue
        tracer.record("cleaning", DEFAULT_TIMINGS["cleaning"])
        tracer.record("chunking", DEFAULT_TIMINGS["chunking"])
        if not embedding_loaded:
            tracer.record("embedding_load", DEFAULT_TIMINGS["embedding_load"])
            embedding_loaded = True
        tracer.record("embedding_encode", DEFAULT_TIMINGS["embedding_encode"])
        tracer.record("database_write", DEFAULT_TIMINGS["database_write"])
        pages.append(page)
    return pages, outcomes, embedding_loaded


def _retrieve_and_select(pages: list[dict], pipeline: str, tracer: StageTracer) -> list[dict]:
    chunks = [deepcopy(chunk) for page in pages for chunk in page.get("chunks", [])]
    tracer.record("fts", DEFAULT_TIMINGS["fts"])
    tracer.record("vector_scan", DEFAULT_TIMINGS["vector_scan"])
    tracer.record("normalization_fusion", DEFAULT_TIMINGS["normalization_fusion"])
    chunks.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    max_chunks, per_source, max_sources = (8, 2, None) if pipeline == "phase1" else (25, 3, 9)
    selected: list[dict] = []
    source_counts: Counter = Counter()
    sources: set[str] = set()
    fingerprints: set[str] = set()
    fingerprint_length = 600 if pipeline == "phase1" else 700
    for chunk in chunks:
        source = str(chunk["source_id"])
        fingerprint = " ".join(chunk["text"].lower().split())[:fingerprint_length]
        if fingerprint in fingerprints or source_counts[source] >= per_source:
            continue
        if max_sources is not None and source not in sources and len(sources) >= max_sources:
            continue
        selected.append(chunk)
        fingerprints.add(fingerprint)
        source_counts[source] += 1
        sources.add(source)
        if len(selected) >= max_chunks:
            break
    tracer.record("diversity_selection", DEFAULT_TIMINGS["diversity_selection"])
    tracer.record("rendering", DEFAULT_TIMINGS["rendering"])
    return selected


def _case_metrics(
    case: dict[str, Any], ranked: list[dict], pages: list[dict], selected: list[dict]
) -> dict:
    search_urls = [item["url"] for item in ranked]
    relevant_urls = set(case.get("relevant_urls", []))
    search_precision, search_recall = precision_recall(search_urls, relevant_urls)
    page_urls = [page["url"] for page in pages]
    _, relevant_page_recall = precision_recall(page_urls, relevant_urls)
    chunk_ids = [str(chunk["id"]) for chunk in selected]
    relevant_chunks = {
        str(chunk["id"])
        for page in case["crawls"].values()
        for chunk in page.get("chunks", [])
        if chunk.get("relevant")
    }
    answer_chunks = set(map(str, case.get("required_chunk_ids", [])))
    chunk_precision, chunk_recall = precision_recall(chunk_ids, relevant_chunks)
    _, answer_recall = precision_recall(chunk_ids, answer_chunks)
    selected_urls = list(
        dict.fromkeys(chunk.get("url", "") for chunk in selected if chunk.get("url"))
    )
    expected_citations = set(case.get("expected_citations", []))
    citation_hits = sum(url in expected_citations for url in selected_urls)
    final_correct = bool(answer_chunks) and answer_chunks.issubset(chunk_ids)
    if case.get("category") == "no_answer":
        final_correct = not any(chunk.get("answer_bearing") for chunk in selected)
    return {
        "search_precision": search_precision,
        "search_recall": search_recall,
        "unique_canonical_sources": len(
            {case["crawls"].get(url, {}).get("canonical_url", url) for url in search_urls}
        ),
        "unique_domains": unique_domains(search_urls),
        "relevant_page_recall": relevant_page_recall,
        "answer_bearing_chunk_recall": answer_recall,
        "chunk_precision": chunk_precision,
        "chunk_recall": chunk_recall,
        "duplicate_rate": duplicate_rate([chunk["text"] for chunk in selected]),
        "source_diversity": safe_ratio(
            len({chunk["source_id"] for chunk in selected}), len(selected)
        ),
        "mrr": reciprocal_rank(search_urls, relevant_urls),
        "ndcg": ndcg(search_urls, relevant_urls),
        "packed_evidence_precision": chunk_precision,
        "citation_support": safe_ratio(citation_hits, len(expected_citations))
        if expected_citations
        else None,
        "final_answer_correctness_proxy": 1.0 if final_correct else 0.0,
    }


def _aggregate_accuracy(case_metrics: list[dict]) -> dict:
    names = [
        "search_precision",
        "search_recall",
        "relevant_page_recall",
        "answer_bearing_chunk_recall",
        "chunk_precision",
        "chunk_recall",
        "duplicate_rate",
        "source_diversity",
        "mrr",
        "ndcg",
        "packed_evidence_precision",
        "final_answer_correctness_proxy",
    ]
    output = {name: mean([float(item[name]) for item in case_metrics]) for name in names}
    citation_values = [
        float(item["citation_support"])
        for item in case_metrics
        if item["citation_support"] is not None
    ]
    output["citation_support"] = mean(citation_values)
    output["citation_support_applicable_cases"] = len(citation_values)
    output["mean_unique_canonical_sources"] = mean(
        [float(item["unique_canonical_sources"]) for item in case_metrics]
    )
    output["mean_unique_domains"] = mean([float(item["unique_domains"]) for item in case_metrics])
    return output


def _run_once(corpus: Corpus, pipeline: str, cold: bool) -> tuple[list[dict], dict, dict]:
    tracer = StageTracer()
    case_metrics: list[dict] = []
    outcomes: Counter = Counter()
    partial = 0
    preserved = 0
    refresh_cases = 0
    embedding_loaded = not cold
    for case in corpus.cases:
        before = len(tracer.events)
        ranked, search_failed = _search(case, pipeline, tracer)
        pages, case_outcomes, embedding_loaded = _crawl(
            case, ranked, pipeline, tracer, embedding_loaded
        )
        outcomes.update(case_outcomes)
        selected = _retrieve_and_select(pages, pipeline, tracer)
        if pipeline == "current":
            if cold:
                tracer.record(
                    "llama_props",
                    DEFAULT_TIMINGS["llama_props"],
                    not case.get("llama_props_failure", False),
                )
            for _ in range(int(case.get("tokenize_calls", 10))):
                tracer.record(
                    "llama_tokenize",
                    DEFAULT_TIMINGS["llama_tokenize"],
                    not case.get("tokenize_failure", False),
                )
        if search_failed or any(key != SUCCESS_OUTCOME for key in case_outcomes):
            partial += 1
        refresh = case.get("failed_refresh")
        if refresh is not None:
            refresh_cases += 1
            preserved += bool(refresh.get("good_content_preserved"))
        case_metrics.append({"id": case["id"], **_case_metrics(case, ranked, pages, selected)})
        duration = sum(event.duration_ms for event in tracer.events[before:])
        tracer.record("total", duration)
    reliability = {
        "crawl_outcomes": dict(sorted(outcomes.items())),
        "partial_result_rate": safe_ratio(partial, len(corpus.cases)),
        "per_stage_failures": tracer.summary()["failure_counts"],
        "good_content_preservation_rate": safe_ratio(preserved, refresh_cases),
        "llama_detection_failure_rate": safe_ratio(
            sum(event.stage == "llama_props" and not event.ok for event in tracer.events),
            sum(event.stage == "llama_props" for event in tracer.events),
        ),
        "llama_tokenization_failure_rate": safe_ratio(
            sum(event.stage == "llama_tokenize" and not event.ok for event in tracer.events),
            sum(event.stage == "llama_tokenize" for event in tracer.events),
        ),
    }
    return case_metrics, reliability, tracer.summary()


def run_offline_benchmark(corpus_path: Path | None = None) -> dict:
    corpus = load_corpus(corpus_path)
    try:
        display_path = str(corpus.path.relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(corpus.path)
    pipelines: dict[str, dict] = {}
    for pipeline in PIPELINES:
        cold_cases, reliability, cold_latency = _run_once(corpus, pipeline, cold=True)
        warm_cases, _, warm_latency = _run_once(corpus, pipeline, cold=False)
        pipelines[pipeline] = {
            "accuracy": _aggregate_accuracy(cold_cases),
            "reliability": reliability,
            "latency": {"cold": cold_latency, "warm": warm_latency},
            "cases": cold_cases,
        }
        assert [item["id"] for item in cold_cases] == [item["id"] for item in warm_cases]
    return {
        "schema_version": "1.0",
        "run_mode": "offline_replay",
        "corpus": {"version": corpus.version, "path": display_path},
        "evaluation_protocol": {
            "final_answer_correctness": "Deterministic selection-readiness proxy: all required answer chunks selected; no LLM judge.",
            "citation_support": "Expected citation URLs represented by selected evidence sources; cases with no citation requirement are null and excluded from the aggregate.",
            "latency": "Recorded deterministic fixture durations, not live wall-clock measurements.",
            "peak_rss_bytes": "Not measured during offline replay; reported as null.",
        },
        "pipelines": pipelines,
        "live_integrations_executed": [],
    }
