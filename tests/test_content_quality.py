from ai_websearch.clean import strip_page_boilerplate
from ai_websearch.content_quality import assess_content_quality


def test_long_consent_content_is_rejected_regardless_of_length() -> None:
    text = " ".join(
        [
            "Manage your privacy. Accept all cookies. Consent preferences include "
            "advertising partners, precise geolocation data, and legitimate interests."
        ]
        * 100
    )
    result = assess_content_quality("Privacy choices", text)
    assert not result.usable
    assert result.outcome == "cookie_consent"
    assert result.reason == "consent_dominant"


def test_article_with_small_cookie_footer_remains_usable() -> None:
    article = " ".join(
        [
            "The field study documents the bridge design, measurement method, "
            "observed vibration, load capacity, and engineering limitations."
        ]
        * 60
    )
    result = assess_content_quality(
        "Independent bridge report",
        article + " Manage your privacy and accept all cookies.",
    )
    assert result.usable
    assert result.reason == "substantive_content"


def test_repeated_generic_navigation_shell_is_rejected() -> None:
    text = " ".join(
        ["Back Button Menu Search Home Account Language Select Close Open More Previous Next"] * 60
    )
    result = assess_content_quality("Back Button", text)
    assert not result.usable
    assert result.reason == "navigation_shell"


def test_realistic_consent_language_is_rejected_per_chunk() -> None:
    text = (
        "Consent to Cookies & Data processing. We and other third parties process data. "
        "Selecting I Accept enables tracking technologies. Reject all or manage preferences. "
        "Store and/or access information on a device. Precise geolocation data and "
        "personalised advertising may be used."
    )
    result = assess_content_quality("Public article", text)
    assert not result.usable
    assert result.outcome == "cookie_consent"


def test_leading_consent_chrome_and_trailing_navigation_are_removed() -> None:
    raw = """Consent to Cookies & Data processing
Selecting I Accept enables tracking technologies. Reject all or manage preferences.
Navigation before the article.
# Public article
The public article contains substantive evidence that must remain available.
## Findings
Measurements confirm the reported result.
## Selected for you
Unrelated recommendation links."""
    assert (
        strip_page_boilerplate(raw)
        == """# Public article
The public article contains substantive evidence that must remain available.
## Findings
Measurements confirm the reported result."""
    )


def test_small_consent_footer_does_not_remove_article_content() -> None:
    article = """# Public cookie policy analysis
The study evaluates consent interfaces and reports reproducible measurements.

Manage your privacy and accept all cookies."""
    assert strip_page_boilerplate(article) == article
