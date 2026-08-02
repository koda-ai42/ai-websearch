from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CORPUS = Path(__file__).with_name("fixtures") / "v1" / "corpus.json"
REQUIRED_CATEGORIES = {
    "exact_factual",
    "technical_documentation",
    "current_events",
    "comparative_consumer",
    "multi_hop",
    "ambiguous",
    "no_answer",
    "conflicting_sources",
    "crawl_access",
}


@dataclass(frozen=True)
class Corpus:
    path: Path
    version: str
    cases: tuple[dict[str, Any], ...]


def load_corpus(path: Path | None = None) -> Corpus:
    selected = (path or DEFAULT_CORPUS).resolve()
    payload = json.loads(selected.read_text(encoding="utf-8"))
    version = payload.get("version")
    cases = payload.get("cases")
    if not isinstance(version, str) or not version:
        raise ValueError("benchmark corpus requires a non-empty version")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark corpus requires at least one case")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ValueError("every benchmark case requires a non-empty id")
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark case ids must be unique")
    categories = {case.get("category") for case in cases}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    if missing:
        raise ValueError(f"benchmark corpus is missing categories: {', '.join(missing)}")
    return Corpus(selected, version, tuple(cases))
