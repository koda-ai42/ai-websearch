from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .content_quality import assess_content_quality

OUTCOMES = {
    "success",
    "cookie_consent",
    "authentication",
    "captcha",
    "subscription",
    "access_denied",
    "robots_denied",
    "http_error",
    "empty_content",
    "extraction_failure",
}

_PATTERNS = {
    "captcha": (
        r"verify (?:that )?you are (?:a )?human",
        r"checking (?:if )?the site connection is secure",
        r"cloudflare ray id",
        r"unusual traffic from your computer network",
        r"(?:enter|solve|complete) (?:the )?captcha",
    ),
    "access_denied": (
        r"\baccess denied\b",
        r"\brequest (?:was )?blocked\b",
        r"\b403 forbidden\b",
        r"you do not have permission to access",
    ),
    "authentication": (
        r"\bsign in to continue\b",
        r"\blog in to continue\b",
        r"\bauthentication required\b",
        r"you must be logged in",
    ),
    "subscription": (
        r"\bsubscribe to continue\b",
        r"\bsubscription required\b",
        r"\bsubscribers? only\b",
        r"continue reading with (?:a|your) subscription",
    ),
    "cookie_consent": (
        r"\bbefore you continue\b",
        r"\bmanage your privacy\b",
        r"\baccept all cookies\b",
        r"\bcookie consent\b",
    ),
}

_STRUCTURAL_MARKERS = {
    "captcha": ("captcha", "challenge-form", "cf-challenge", "turnstile"),
    "authentication": ("login-form", "signin-form", "auth-form"),
    "subscription": ("paywall", "subscription-wall", "subscriber-gate"),
    "access_denied": ("access-denied", "forbidden", "request-blocked"),
}


def _structural_outcome(soup: BeautifulSoup | None) -> str | None:
    if soup is None:
        return None
    for element in soup.find_all(True):
        attributes = " ".join(
            [
                str(element.get("id") or ""),
                " ".join(str(item) for item in (element.get("class") or [])),
                str(element.get("data-testid") or ""),
            ]
        ).casefold()
        for outcome, markers in _STRUCTURAL_MARKERS.items():
            if any(marker in attributes for marker in markers):
                return outcome
        if element.name == "input" and str(element.get("type") or "").casefold() == "password":
            return "authentication"
    return None


def classify_access_outcome(title: str, html: str | None, markdown: str) -> str:
    soup = BeautifulSoup(html, "html.parser") if html else None
    html_text = soup.get_text(" ", strip=True) if soup else ""
    text = " ".join((title, html_text, markdown)).casefold()
    structural = _structural_outcome(soup)
    if structural is not None:
        return structural
    body_word_count = len((html_text + " " + markdown).split())
    if "captcha" in title.casefold() and body_word_count < 400:
        return "captcha"
    if body_word_count < 400:
        for outcome in ("captcha", "access_denied", "authentication", "subscription"):
            if any(re.search(pattern, text) for pattern in _PATTERNS[outcome]):
                return outcome
    # Cookie language is common in page footers; the deterministic quality
    # assessment rejects it only when consent material dominates the page.
    if len(markdown.split()) < 400 and any(
        re.search(pattern, text) for pattern in _PATTERNS["cookie_consent"]
    ):
        return "cookie_consent"
    quality = assess_content_quality(title, markdown or html_text)
    if not quality.usable:
        return quality.outcome
    return "success"
