from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
}

PROMPT_INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior) instructions",
    r"system prompt",
    r"developer message",
    r"reveal (the )?(secret|api key|password)",
    r"tool call",
    r"send .*credentials",
]

_LEADING_CONSENT = re.compile(
    r"\b(?:consent to cookies|selecting [\"']?i accept|reject all|"
    r"manage preferences|tracking technologies|precise geolocation)\b",
    re.I,
)
_ARTICLE_HEADING = re.compile(r"^#\s+\S")
_TRAILING_SITE_SECTION = re.compile(
    r"^#{2,3}\s+(?:selected for you|services links and disclaimer)\s*$",
    re.I,
)


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    cleaned = parts._replace(query=urlencode(query), fragment="")
    return urlunsplit(cleaned)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def clean_markdown(markdown: str) -> str:
    text = unescape(markdown or "")
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"!\[\]\([^)]*\)", "", text)

    lines = []
    seen_blank = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if not seen_blank:
                lines.append("")
            seen_blank = True
            continue
        seen_blank = False
        lines.append(stripped)
    return "\n".join(lines).strip()


def strip_page_boilerplate(markdown: str) -> str:
    """Remove high-confidence consent chrome while preserving public article content."""

    text = clean_markdown(markdown)
    if not text:
        return ""
    lines = text.splitlines()
    leading_sample = "\n".join(lines[:20])
    if len(_LEADING_CONSENT.findall(leading_sample)) >= 2:
        article_start = next(
            (index for index, line in enumerate(lines) if _ARTICLE_HEADING.match(line)),
            None,
        )
        if article_start is not None:
            lines = lines[article_start:]

    trailing_start = next(
        (index for index, line in enumerate(lines[1:], 1) if _TRAILING_SITE_SECTION.match(line)),
        None,
    )
    if trailing_start is not None:
        lines = lines[:trailing_start]
    return clean_markdown("\n".join(lines))


def find_prompt_injection_markers(text: str) -> list[str]:
    lowered = text.lower()
    markers = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            markers.append(pattern)
    return markers
