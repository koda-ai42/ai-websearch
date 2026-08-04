from __future__ import annotations

import re
from dataclasses import dataclass

QUALITY_POLICY_VERSION = 3

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_CONSENT_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\baccept all cookies\b",
        r"\bconsent to cookies\b",
        r"\bmanage your privacy\b",
        r"\bmanage preferences\b",
        r"\bconsent preferences?\b",
        r"\blegitimate interests?\b",
        r"\blist of iab vendors\b",
        r"\bpartners? can use (?:this|that) (?:feature|purpose)\b",
        r"\bprecise geolocation data\b",
        r"\bscan device characteristics\b",
        r"\bstore and(?:/or)? access information on a device\b",
        r"\bselecting [\"']?i accept\b",
        r"\breject all\b",
        r"\btracking technologies\b",
        r"\bother third parties process data\b",
        r"\bpersonalised advertising\b",
        r"\badvertising (?:partners?|purposes?|preferences?)\b",
        r"\bconsent (?:purposes?|settings|choices)\b",
        r"\bvendors? purposes?\b",
        # IAB / vendor-specific identifiers (language-neutral)
        r"\biab vendors?\b",
        r"\biab vendor list\b",
        r"\btc string\b",
        r"\bglobal string\b",
        r"\bconsent string\b",
        r"\bpurpose ids?\b",
        r"\bvendor ids?\b",
        r"\bconsent management platform\b",
        r"\bcmp id\b",
    )
)


def _has_sentence_ending(text: str) -> bool:
    return bool(re.search(r"[.!?:]", text))


@dataclass(frozen=True)
class ContentQualityAssessment:
    usable: bool
    outcome: str
    reason: str
    word_count: int
    consent_signals: int


def _consent_signal_count(text: str) -> int:
    return sum(len(pattern.findall(text)) for pattern in _CONSENT_PATTERNS)


def assess_content_quality(title: str, text: str) -> ContentQualityAssessment:
    """Reject high-confidence access boilerplate without inspecting cookie data."""

    words = _WORD.findall(text.casefold())
    word_count = len(words)
    if not words:
        return ContentQualityAssessment(False, "access_denied", "no_substantive_content", 0, 0)

    consent_signals = _consent_signal_count(text)
    signals_per_hundred_words = consent_signals * 100.0 / word_count
    if consent_signals >= 3 and signals_per_hundred_words >= 1.0:
        return ContentQualityAssessment(
            False,
            "cookie_consent",
            "consent_dominant",
            word_count,
            consent_signals,
        )

    unique_ratio = len(set(words)) / word_count
    if (
        word_count >= 20
        and word_count <= 500
        and unique_ratio < 0.12
        and not _has_sentence_ending(text)
    ):
        return ContentQualityAssessment(
            False,
            "access_denied",
            "navigation_shell",
            word_count,
            consent_signals,
        )

    return ContentQualityAssessment(
        True, "success", "substantive_content", word_count, consent_signals
    )
