# Access-classifier benchmark

Recorded 2026-08-02 against Stage 12 corpus `2026-08-02.v2`.

| Metric | Before | After |
|---|---:|---:|
| Crawl-outcome accuracy | 0.8 | 1.0 |
| Legitimate-article acceptance | 0.4 | 1.0 |
| Wall rejection | 1.0 | 1.0 |
| Evidence-gate accuracy | 1.0 | 1.0 |

The 30 crawl cases cover success, consent, authentication, CAPTCHA,
subscription and access-denied outcomes. Six long public articles discussing
wall wording were previously false positives. Phrase-only classification is now
limited to short/dominant pages; rendered structural wall markers remain
terminal. This is deterministic offline policy coverage, not a live browser
accuracy claim.
