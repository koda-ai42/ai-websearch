from __future__ import annotations

import re
from urllib.parse import urlsplit

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
    "cookie_consent": (
        # Existing
        # Cookiebot / default CMP
        "cc-window",
        "cookieconsent",
        # OneTrust
        "onetrust-banner-sdk",
        "onetrust",
        # Osano
        "osano-cm",
        # Usercentrics
        "usercentrics-root",
        # CookieLawInfo
        "cookielawinfo",
        # Privacy-related banners
        "privacy-notice",
        "privacy-banner",
        "gdpr-banner",
        # TCF / consent
        "tcfelement",
        "cookie-policy",
        # Cloudflare
        "cf-cookie-alert",
        # Generic
        "cookie-banner",
        "cookie-notice",
    ),
    "captcha": (
        # Existing
        "captcha",
        "challenge-form",
        "cf-challenge",
        "turnstile",
        # Google reCAPTCHA
        "g-recaptcha",
        "recaptcha-checkbox",
        "recaptcha-widget",
        # Cloudflare Turnstile
        "cf-turnstile-widget",
        "cf-turnstile",
        "cf-challenge-running",
        "cf-browser-verification",
        # hCaptcha
        "h-captcha",
        "hcaptcha-widget",
        # BrowserStack / BrowserStack captcha
        "brcaptcha",
        "challenge-container",
    ),
    "authentication": (
        # Existing
        "login-form",
        "signin-form",
        "auth-form",
        # Additional field markers
        "password-input",
        "username-field",
        "email-field",
        "auth-container",
        "sign-in-btn",
        "signin-btn",
        "login-btn",
        "auth-form-container",
        "credentials-form",
    ),
    "subscription": (
        # Existing
        "paywall",
        "subscription-wall",
        "subscriber-gate",
        # Additional
        "paywall-overlay",
        "subscription-modal",
        "subscriber-only",
        "premium-content",
        "gated-content",
        "register-wall",
        "paywall-gate",
        "locked-content",
        "members-only",
        "vip-content",
    ),
    "access_denied": (
        # Existing
        "access-denied",
        "forbidden",
        "request-blocked",
        # Additional
        "error-page",
        "blocked-page",
        "waf-block",
        "security-block",
        "access-restricted",
        "ip-blocked",
        "rate-limited",
    ),
}

_VENDOR_DOMAINS = {
    "cookie_consent": (
        "cookiebot.com",
        "cookielaw.org",
        "onetrust.com",
        "usercentrics.eu",
        "osano.com",
        "didomi.io",
        "consentmanager.net",
        "privacy-center.org",
        "cybercookielist.com",
        "consentip.com",
        "consentframework.com",
        "cmp.consensu.org",
    ),
    "captcha": (
        "google.com/recaptcha",
        "recaptcha.net",
        "challenges.cloudflare.com",
        "hcaptcha.com",
        "brcdn.com",
        "brecaptcha.net",
    ),
    "subscription": (
        "paywall",
        "subscribe",
        "premium",
    ),
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


def _vendor_outcome(soup: BeautifulSoup | None) -> str | None:
    if soup is None:
        return None
    for element in soup.find_all(["iframe", "script", "link"]):
        src = str(element.get("src") or element.get("href") or "").casefold()
        if not src or src.startswith("#"):
            continue
        parsed = urlsplit(src)
        hostname = (parsed.hostname or "").casefold()
        path = (parsed.path or "").casefold()
        full = hostname + path
        for outcome, domains in _VENDOR_DOMAINS.items():
            if outcome == "subscription":
                if any(keyword in path for keyword in domains):
                    return outcome
            else:
                if any(domain in hostname or domain in full for domain in domains):
                    return outcome
    return None


def classify_access_outcome(title: str, html: str | None, markdown: str) -> str:
    soup = BeautifulSoup(html, "html.parser") if html else None
    html_text = soup.get_text(" ", strip=True) if soup else ""
    text = " ".join((title, html_text, markdown)).casefold()
    structural = _structural_outcome(soup)
    if structural is not None:
        return structural
    vendor = _vendor_outcome(soup)
    if vendor is not None:
        return vendor
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
