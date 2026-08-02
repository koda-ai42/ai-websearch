from __future__ import annotations

import re
from dataclasses import dataclass

from .content_quality import assess_content_quality
from .models import ContextChunk

QUESTION_STOPWORDS = {
    "about",
    "after",
    "also",
    "are",
    "can",
    "could",
    "does",
    "for",
    "from",
    "have",
    "how",
    "into",
    "its",
    "should",
    "that",
    "the",
    "their",
    "then",
    "this",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
}
COMPLEX_MARKERS = re.compile(
    r"\b(compare|versus|trade-?offs?|analy[sz]e|evaluate|synthesi[sz]e|multi-step|"
    r"advantages and disadvantages|pros and cons)\b",
    re.I,
)


@dataclass(frozen=True)
class EvidenceAssessment:
    sufficient: bool
    reason: str
    source_count: int
    chunk_count: int
    query_coverage: float

    def metadata(self) -> dict:
        return {
            "sufficient": self.sufficient,
            "reason": self.reason,
            "source_count": self.source_count,
            "chunk_count": self.chunk_count,
            "query_coverage": round(self.query_coverage, 4),
        }


def query_is_complex(query: str) -> bool:
    words = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
    question_clauses = len([part for part in re.split(r"[;?]+", query) if len(part.split()) >= 3])
    return bool(COMPLEX_MARKERS.search(query) or question_clauses > 1 or len(words) > 28)


def initial_pass(requested_mode: str) -> str:
    mode = requested_mode.casefold().strip()
    if mode not in {"rapid", "deep", "auto"}:
        raise ValueError("mode must be rapid, deep, or auto")
    if mode != "auto":
        return mode
    return "rapid"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
        if len(token) > 2 and token not in QUESTION_STOPWORDS
    }


def assess_evidence(
    query: str, chunks: list[ContextChunk], *, complex_query: bool | None = None
) -> EvidenceAssessment:
    if not chunks:
        return EvidenceAssessment(False, "no_usable_evidence", 0, 0, 0.0)
    considered = [
        chunk for chunk in chunks[:8] if assess_content_quality(chunk.title, chunk.text).usable
    ]
    if not considered:
        return EvidenceAssessment(False, "content_quality_insufficient", 0, 0, 0.0)
    sources = {chunk.source_id for chunk in considered}
    query_tokens = _tokens(query)
    evidence_tokens: set[str] = set()
    for chunk in considered:
        evidence_tokens.update(_tokens(chunk.title + " " + chunk.text))
    coverage = len(query_tokens & evidence_tokens) / len(query_tokens) if query_tokens else 1.0
    complex_query = query_is_complex(query) if complex_query is None else complex_query

    if complex_query and len(sources) < 2:
        return EvidenceAssessment(
            False, "complex_query_needs_source_diversity", len(sources), len(considered), coverage
        )
    dual_channel = any(
        chunk.vector_rank is not None and chunk.keyword_rank is not None for chunk in considered[:3]
    )
    # Agreement between dense and keyword retrieval is useful corroboration,
    # but one source can make both channels agree on the same weak passage.
    # Low lexical coverage therefore also requires source diversity.
    if coverage < 0.30 and not (dual_channel and len(sources) >= 2):
        return EvidenceAssessment(
            False, "low_query_coverage", len(sources), len(considered), coverage
        )
    return EvidenceAssessment(True, "sufficient_evidence", len(sources), len(considered), coverage)
